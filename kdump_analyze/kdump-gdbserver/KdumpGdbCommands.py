import json
import os


# We don't want to polute gdb python namespace with our helper function so
# put them into separate class as staticmethods
class KdumpGdbserverBase:
    """
    Collection of static methods used by multiple commands,
    compiled into a class to avoid polluting gdb's python
    name space
    """

    @staticmethod
    def offsetof(parent, field):
        """find offset of field within given parent structure"""
        return parent[field].bitpos // 8

    @staticmethod
    def container_of(ptr, ctype, member):
        """retrieve structure address with pointer to given field"""
        void_ptr_type = gdb.lookup_type("void").pointer()
        return (ptr.cast(void_ptr_type) - KdumpGdbserverBase.offsetof(ctype, member)).cast(ctype.pointer())

    @staticmethod
    def kernellist(start, field, stype, include_first=False):
        """generator to walk kernel list"""
        if start.type.code != gdb.TYPE_CODE_PTR:
            start = start.address

        current = start
        if include_first:
            yield KdumpGdbserverBase.container_of(current, stype, field)

        current = current["next"]
        while current != start:
            yield KdumpGdbserverBase.container_of(current, stype, field)
            current = current["next"]

    @staticmethod
    def get_thread_info(task, pid, regs, threads):
        """return basic thread info as dictionary"""
        comm = task["comm"].string()
        if int(task['mm']) == 0:
            comm = "[" + comm + "]"
        tid = int(task["pid"])

        thread = {
            "pid": pid,
            "tid": tid,
            "comm": comm,
            "registers": regs}
        threads.append(thread)
        return threads


class KdumpGdbserverKernelPs(gdb.Command):
    """list all tasks in current kernel

Command outputs information on all processes similar to "ps -efL" command
    """

    def __init__(self):
        super(KdumpGdbserverKernelPs, self).__init__("kdump-kernel-ps", gdb.COMMAND_USER)

    @staticmethod
    def print_ps(gvalue, pid):
        """print process information in "ps -efL" kind of format, plus task_struct ptr"""
        uid = int(gvalue['real_cred']['uid']['val'])
        ppid = int(gvalue['parent']['pid'])
        lwp = int(gvalue['pid'])

        comm = gvalue['comm'].string()
        if int(gvalue['mm']) == 0:
            comm = "[" + comm + "]"

        address = str(gvalue).split()[0]

        print('{:<10d} {:<10d} {:<10d} {:<10d} {:<25s} {:<16s}'.format(uid, pid, ppid, lwp, comm, address))

    def invoke(self, arg, from_tty):
        init_task = gdb.parse_and_eval("init_task")
        print('{:<10s} {:<10s} {:<10s} {:<10s} {:<25s} {:<16s}'.format("UID", "PID", "PPID", "LWP", "COMM", "ADDRESS"))
        for task in KdumpGdbserverBase.kernellist(init_task["tasks"], "tasks", init_task.type, include_first=True):
            pid = int(task["pid"])
            KdumpGdbserverKernelPs.print_ps(task, pid)
            # needs to walk all threads for this pid if any
            for ctask in KdumpGdbserverBase.kernellist(task["thread_group"], "thread_group", init_task.type):
                KdumpGdbserverKernelPs.print_ps(ctask, pid)


class KdumpGdbserverMakeProcessJson(gdb.Command):
    """generates kdump-gdbserver process json file

This command given a process id and file name will
generate a json file containing information necessary for
kdump-gdbserver to run in process mode

usage: kdump-save-process-json <filename> <pid>"""

    def __init__(self):
        super(KdumpGdbserverMakeProcessJson, self).__init__("kdump-save-process-json",
                                                            gdb.COMMAND_USER,
                                                            gdb.COMPLETE_FILENAME)
        self.ARCH_USR_REGS_FUNC = {
            "aarch64": KdumpGdbserverMakeProcessJson.get_thread_regs_aarch64,
            "riscv:rv64": KdumpGdbserverMakeProcessJson.get_thread_regs_riscv64,
            "i386:x86-64": KdumpGdbserverMakeProcessJson.get_thread_regs_x86_64,
        }

    @staticmethod
    def get_first_exec_addr(task):
        """Find first executable section of memory to find process start"""
        current_mm = task['mm']['mmap']

        while current_mm != 0:
            flags = int(current_mm['vm_flags'])
            if flags & 4:
                return current_mm['vm_start']
            current_mm = current_mm['vm_next']

    @staticmethod
    def findtask(pid):
        """Locate task struct of process with given pid"""
        tpid = int(pid)
        init_task = gdb.parse_and_eval("init_task")
        for task in KdumpGdbserverBase.kernellist(init_task["tasks"], "tasks", init_task.type, include_first=True):
            if int(task['pid']) == tpid:
                return task
            for ctask in KdumpGdbserverBase.kernellist(task["thread_group"], "thread_group", init_task.type):
                if int(ctask['pid']) == tpid:
                    # note returns leading task, not the one that matches requested pid
                    return task

    @staticmethod
    def get_thread_regs_aarch64(task):
        """read user-land registers for aarch64 architecture"""

        # find pointer to struct pt_regs on current task stack. It is pretty
        # much implementation of task_pt_regs macro from arch/arm64/include/asm/processor.h
        # #define task_pt_regs(p) \
        #    ((struct pt_regs *)(THREAD_SIZE + task_stack_page(p)) - 1)
        # Note values we use may not work for kernel built with CONFIG_KASAN
        # TODO: look at kasan case
        eval_string = "((struct pt_regs *)(0x4000 + (void *) (((struct task_struct *)0x%x)->stack)) - 1)" % (task)
        pt_regs = gdb.parse_and_eval(eval_string)

        regs = {}
        for x in range(31):
            regs["x%d" % (x)] = int(pt_regs["user_regs"]["regs"][x])
        regs["sp"] = int(pt_regs["user_regs"]["sp"])
        regs["pc"] = int(pt_regs["user_regs"]["pc"])
        regs["cpsr"] = int(pt_regs["user_regs"]["pstate"])
        return regs

    def get_thread_regs_riscv64(task):
        """read user-land registers for riscv64 architecture"""

        # find pointer to struct pt_regs on current task stack. It is pretty
        # much implementation of task_pt_regs macro from arch/riscv/include/asm/processor.h
        # #define task_pt_regs(tsk)						\
        # 	((struct pt_regs *)(task_stack_page(tsk) + THREAD_SIZE		\
        # 			    - ALIGN(sizeof(struct pt_regs), STACK_ALIGN)))
        # Note values we use may not work for kernel built with CONFIG_KASAN
        # TODO: look at kasan case
        eval_string = "((struct pt_regs *)(0x4000 + (void *) (((struct task_struct *)0x%x)->stack)) - 1)" % (task)
        pt_regs = gdb.parse_and_eval(eval_string)

        regs = {}
        aregs = ("a%d" % (x) for x in range(8))
        sregs = ("s%d" % (x) for x in range(1, 12))
        tregs = ("t%d" % (x) for x in range(7))
        for reg_name in ("ra", "sp", "gp", "tp", *aregs, *sregs, *tregs):
            regs[reg_name] = int(pt_regs[reg_name])
        regs["fp"] = int(pt_regs["s0"])
        regs["pc"] = int(pt_regs["epc"])
        return regs

    @staticmethod
    def get_thread_regs_x86_64(task):
        """read user-land registers for x86_64 architecture"""

        # find pointer to struct pt_regs on current task stack. It is pretty
        # much implementation of task_pt_regs macro from arch/x86/include/asm/processor.h
        # #define task_pt_regs(task)
        # ({									\
        #	unsigned long __ptr = (unsigned long)task_stack_page(task);	\
        #	__ptr += THREAD_SIZE - TOP_OF_KERNEL_STACK_PADDING;		\
        #	((struct pt_regs *)__ptr) - 1;					\
        # })
        # Note values we use may not work for kernel built with CONFIG_KASAN
        # TODO: look at kasan case
        eval_string = "((struct pt_regs *)(0x4000 + (void *) (((struct task_struct *)0x%x)->stack)) - 1)" % (task)
        pt_regs = gdb.parse_and_eval(eval_string)

        regs = {}
        for x in range(8, 16):
            regs["r%d" % (x)] = int(pt_regs["r%d" % (x)])
        regs["eflags"] = int(pt_regs["flags"])
        regs["cs"] = int(pt_regs["cs"])
        regs["ss"] = int(pt_regs["ss"])
        regs["rbp"] = int(pt_regs["bp"])
        regs["rax"] = int(pt_regs["ax"])
        regs["rbx"] = int(pt_regs["bx"])
        regs["rcx"] = int(pt_regs["cx"])
        regs["rdx"] = int(pt_regs["dx"])
        regs["rsi"] = int(pt_regs["si"])
        regs["rdi"] = int(pt_regs["di"])
        regs["rip"] = int(pt_regs["ip"])
        regs["rsp"] = int(pt_regs["sp"])

        return regs

    @staticmethod
    def write_to_json(rootpgt, thread, loadaddr, filename):
        """given information generate json file"""
        dic = {"rootpgt": rootpgt, "loadaddr": loadaddr, "threads": thread}
        with open(filename, 'w') as json_file:
            json.dump(dic, json_file, indent=4)

    def invoke(self, arg, from_tty):
        args = arg.split(" ")

        arch = gdb.inferiors()[0].architecture().name()
        thread_reg_func = self.ARCH_USR_REGS_FUNC[arch]

        filename = args[0]
        filename = os.path.expanduser(filename)
        pid = args[1]
        task = KdumpGdbserverMakeProcessJson.findtask(pid)
        if task == None:
            print("No task with pid", pid, "use kdump-kernel-ps to find available pids")
        else:
            pid = int(task["pid"])
            rootpgt = int(task["mm"]["pgd"])
            loadaddr = int(KdumpGdbserverMakeProcessJson.get_first_exec_addr(task))
            threads = []
            task_type = gdb.parse_and_eval("init_task").type
            for ctask in KdumpGdbserverBase.kernellist(task["thread_group"], "thread_group", task_type, include_first=True):
                regs = thread_reg_func(ctask)
                threads = KdumpGdbserverBase.get_thread_info(ctask, pid, regs, threads)
            KdumpGdbserverMakeProcessJson.write_to_json(rootpgt, threads, loadaddr, filename)


class KdumpGdbserverMakeKernelJson(gdb.Command):
    """generates kdump-gdbserver kernel json file

This command given a file name will generate a json file
containing information necessary for kdump-gdbserver to run
in kernel with tasks mode, i.e where all kernel tasks
presented as threads

usage: kdump-save-kernel-json <filename>"""

    def __init__(self):
        super(KdumpGdbserverMakeKernelJson, self).__init__("kdump-save-kernel-json",
                                                           gdb.COMMAND_USER,
                                                           gdb.COMPLETE_FILENAME)
        self.ARCH_KER_REGS_FUNC = {
            "aarch64": KdumpGdbserverMakeKernelJson.get_thread_regs_ker_aarch64,
            "riscv:rv64": KdumpGdbserverMakeKernelJson.get_thread_regs_ker_riscv64,
            "i386:x86-64": KdumpGdbserverMakeKernelJson.get_thread_regs_ker_x86_64,
        }

    @staticmethod
    def get_thread_regs_ker_aarch64(task):
        """read kernel task registers used by scheduler for aarch64 architecture"""
        cpu_context = task["thread"]["cpu_context"]
        regs = {}
        for x in range(31):
            reg_num = "x%d" % (x)
            try:
                regs[reg_num] = int(cpu_context[reg_num])
            except gdb.error:
                pass
        regs["x29"] = int(cpu_context["fp"])
        regs["sp"] = int(cpu_context["sp"])
        regs["pc"] = int(cpu_context["pc"])
        return regs

    @staticmethod
    def get_thread_regs_ker_riscv64(task):
        """read kernel task registers used by scheduler for riscv64 architecture"""
        thread = task["thread"]

        regs = {}
        for x in range(12):
            try:
                regs["s%d" % (x)] = int(thread["s"][x])
            except gdb.error:
                pass
        regs["pc"] = int(thread["ra"])
        regs["sp"] = int(thread["sp"])
        return regs

    @staticmethod
    def get_thread_regs_ker_x86_64(task):
        """read kernel task registers used by scheduler for x86_64 architecture"""
        thread = task["thread"]
        rsp = thread["sp"]
        inactive_task_frame_p_type = gdb.lookup_type("struct inactive_task_frame").pointer()
        frame = rsp.cast(inactive_task_frame_p_type)

        regs = {}
        regs["rsp"] = int(rsp)
        regs["rip"] = int(frame['ret_addr'])
        regs['rbp'] = int(frame['bp'])
        regs['rbx'] = int(frame['bx'])
        regs['r12'] = int(frame['r12'])
        regs['r13'] = int(frame['r13'])
        regs['r14'] = int(frame['r14'])
        regs['r15'] = int(frame['r15'])
        return regs

    @staticmethod
    def write_to_json(thread, filename):
        """given information generate json file"""
        dic = {"threads": thread}
        with open(filename, 'w') as json_file:
            json.dump(dic, json_file, indent=4)

    def invoke(self, arg, from_tty):
        args = arg.split(" ")
        filename = args[0]
        filename = os.path.expanduser(filename)
        arch = gdb.inferiors()[0].architecture().name()
        thread_reg_func = self.ARCH_KER_REGS_FUNC[arch]

        init_task = gdb.parse_and_eval("init_task")
        threads = []
        task_type = init_task.type
        for task in KdumpGdbserverBase.kernellist(init_task["tasks"], "tasks", task_type, include_first=True):
            pid = int(task["pid"])
            for ctask in KdumpGdbserverBase.kernellist(task["thread_group"], "thread_group", task_type,
                                                       include_first=True):
                regs = thread_reg_func(ctask)
                threads = KdumpGdbserverBase.get_thread_info(ctask, pid, regs, threads)
        KdumpGdbserverMakeKernelJson.write_to_json(threads, filename)


KdumpGdbserverKernelPs()
KdumpGdbserverMakeProcessJson()
KdumpGdbserverMakeKernelJson()
