kdump-gdbserver
===============

**NOTE:** This program uses the 
[pykdumpfile](https://pypi.org/project/pykdumpfile/)
API, not the legacy bindings included with libkdumpfile.

Introduction
------------

kdump-gdbserver is a symbol debugging tool similar to
[crash](https://github.com/crash-utility/crash.git) or
[crash-python](https://github.com/crash-python/crash-python).
It allows inspection of kernel crash dump file (aka
kernel vmcore) with gdb. It uses
[gdb remote debugging protocol](https://sourceware.org/gdb/current/onlinedocs/gdb/Remote-Protocol.html)
to convey information from vmcore file to gdb. Typical usage pattern is to start
kdump-gdbserver with a certain vmcore file. Kdump-gdbserver will be listening on a
port and then connect via gdb 'target remote' command.

kdump-gdbserver server can operate in one of the three following modes:

1. kernel - primary mode, gdb can read kernel memory translated through the
kernel page table, and each cpu core is presented as a separate thread

2. kernel with tasks - same as kernel mode but also all kernel tasks will be
presented as threads. To operate in this mode kdump-gdbserver needs
information about all kernel tasks registers which is passed in an additional
json file that should be generated in kernel mode.

3. process mode - if vmcore contains user-land processes pages kdump-gdbserver
can present this process address space and its threads. It would present the
same view to gdb as one can get from regular user-land process core. And it
could be done for any user-land process present in kernel crash moment. Similar
to kernel with tasks mode this mode also requires a json file with additional
information that can be generated in kernel mode.

In order to extract information needed for kernel with tasks mode and process mode
KdumpGdbCommands.py python script is provided. How to use script to extract correct
data is detailed in each relevant mode's section.

Kernel Mode
-----------

Start kdump-gdbserver and provide path to vmcore with -f option:

    $ kdump-gdbserver -f vmcore
    Waiting for incoming connection on localhost port 1234
    In gdb execute the following command(s) to connect:
    file <vmlinux> -o 0x9200000
    target remote localhost:1234


Start proper gdb and execute commands suggested by kdump-gdbserver. Use vmlinux
kernel symbol file that corresponds to given vmcore file.

    $ gdb
    <snip>
    (gdb) file vmlinux -o 0x9200000
    Reading symbols from vmlinux...
    (gdb) target remote localhost:1234
    Remote debugging using localhost:1234
    crash_setup_regs (oldregs=<optimized out>, newregs=<optimized out>) at /usr/src/kernel/arch/x86/include/asm/kexec.h:95
    95	/usr/src/kernel/arch/x86/include/asm/kexec.h: No such file or directory.
    (gdb) bt
     #0  crash_setup_regs (oldregs=<optimized out>, newregs=<optimized out>) at /usr/src/kernel/arch/x86/include/asm/kexec.h:95
     #1  __crash_kexec (regs=0x0) at /usr/src/kernel/kernel/kexec_core.c:958
     #2  0xffffffff8a275e98 in panic (fmt=0xffffffff8b47af59 "sysrq triggered crash\n") at /usr/src/kernel/kernel/panic.c:251
     #3  0xffffffff8a8a547a in sysrq_handle_crash (key=<optimized out>) at /usr/src/kernel/drivers/tty/sysrq.c:153
     #4  0xffffffff8a8a5e67 in __handle_sysrq (key=99, check_mask=false) at /usr/src/kernel/drivers/tty/sysrq.c:571


Note in this example kernel was operating in KASLR mode so it is important to use
'-o' option in file command with value suggested by kdump-gdbserver. It is
extracted from vmcore VMCOREINFO note KERNELOFFSET value.

Now you can inspect state of kernel crash! For example we can see what was executing
on other cores:

    (gdb) info threads
    Id   Target Id                   Frame
    * 1    Thread 1.1 (CPU #0 pid 386) crash_setup_regs (oldregs=<optimized out>, newregs=<optimized out>)
        at /usr/src/kernel/arch/x86/include/asm/kexec.h:95
    2    Thread 1.2 (CPU #1 idle)    mwait_idle () at /usr/src/kernel/arch/x86/kernel/process.c:806
    3    Thread 1.3 (CPU #2 idle)    0xffffffff8a2a763e in preempt_count_add (val=1)
        at /usr/src/kernel/arch/x86/include/asm/preempt.h:26
    4    Thread 1.4 (CPU #3 idle)    mwait_idle () at /usr/src/kernel/arch/x86/kernel/process.c:806

Kernel with Tasks
-----------------

Sometimes one would want to see backtrace and investigate stack state of
specific kernel tasks. All required information, task data and their
register sets are in vmcore but it needs to be extracted using kernel symbolic
information. For this purpose KdumpGdbCommands.py gdb python script is provided.

In simple kernel mode the script needs to be sourced:

    (gdb) source KdumpGdbCommands.py

And kdump-save-kernel-json command should be used to generate kernel tasks state
json file:

    (gdb) kdump-save-kernel-json kernel-tasks.json

After that exit from Kdump-gdbserver and restart it with additional option. Provide
the json file that was generated with -k command line option:

    $ kdump-gdbserver -f vmcore -k kernel-tasks.json
    Waiting for incoming connection on localhost port 1234
    In gdb execute the following command(s) to connect:
    file <vmlinux> -o 0x9200000
    target remote localhost:1234

Now you can see all kernel tasks loaded as threads in gdb:

    (gdb) info threads
    Id   Target Id                                         Frame
    * 1    Thread 1.1 (pid 386 LWP 386 "sh")                 crash_setup_regs (oldregs=<optimized out>, newregs=<optimized out>)
        at /usr/src/kernel/arch/x86/include/asm/kexec.h:95
      2    Thread 1.2 (pid 0 LWP 0 "[swapper/0]")            mwait_idle () at /usr/src/kernel/arch/x86/kernel/process.c:806
      3    Thread 1.3 (pid 0 LWP 0 "[swapper/0]")            0xffffffff8a2a763e in preempt_count_add (val=1)
        at /usr/src/kernel/arch/x86/include/asm/preempt.h:26
      4    Thread 1.4 (pid 0 LWP 0 "[swapper/0]")            mwait_idle () at /usr/src/kernel/arch/x86/kernel/process.c:806
      5    Thread 1.5 (pid 1 LWP 1 "init")                   0xffffffff8ade1feb in context_switch (rf=<optimized out>,
        next=<optimized out>, prev=<optimized out>, rq=<optimized out>) at /usr/src/kernel/kernel/sched/core.c:3546
      6    Thread 1.6 (pid 2 LWP 2 "[kthreadd]")             0xffffffff8ade1feb in context_switch (rf=<optimized out>,
        next=<optimized out>, prev=<optimized out>, rq=<optimized out>) at /usr/src/kernel/kernel/sched/core.c:3546
      7    Thread 1.7 (pid 3 LWP 3 "[rcu_gp]")               0xffffffff8ade1feb in context_switch (rf=<optimized out>,
    <snip>
      84   Thread 1.84 (pid 311 LWP 311 "[nfsd]")            0xffffffff8ade1feb in context_switch (rf=<optimized out>,
        next=<optimized out>, prev=<optimized out>, rq=<optimized out>) at /usr/src/kernel/kernel/sched/core.c:3546

Inspect task stack at will:

    (gdb) thread 84
    [Switching to thread 84 (Thread 1.84)]
    #0  0xffffffff8ade1feb in context_switch (rf=<optimized out>, next=<optimized out>, prev=<optimized out>,
        rq=<optimized out>) at /usr/src/kernel/kernel/sched/core.c:3546
    3546	in /usr/src/kernel/kernel/sched/core.c
    (gdb) bt
    #0  0xffffffff8ade1feb in context_switch (rf=<optimized out>, next=<optimized out>, prev=<optimized out>,
        rq=<optimized out>) at /usr/src/kernel/kernel/sched/core.c:3546
    #1  __schedule (preempt=<optimized out>) at /usr/src/kernel/kernel/sched/core.c:4307
    #2  0xffffffff8ade23ef in schedule () at /usr/src/kernel/kernel/sched/core.c:4382
    #3  0xffffffff8ade5a60 in schedule_timeout (timeout=<optimized out>) at /usr/src/kernel/kernel/time/timer.c:1916
    #4  0xffffffff8adbfda9 in svc_get_next_xprt (timeout=<optimized out>, rqstp=<optimized out>)
        at /usr/src/kernel/net/sunrpc/svc_xprt.c:733
    #5  svc_recv (rqstp=0xffffa08dec59c000, timeout=<optimized out>) at /usr/src/kernel/net/sunrpc/svc_xprt.c:850


Process
-------

If kernel dump file was captured with user data pages information about any process
state is all there. kdump-gdbsever can use process specific page table root, find
user-land threads registers and present process core view as one would get from
regular core file. Similar to kernel with tasks mode this additional information
must be extracted. For this purpose use the KdumpGdbCommands.py gdb python script
provided.

In simple kernel mode the script needs to be sourced:

    (gdb) source KdumpGdbCommands.py

To find the PID of the process you want to debug use kdump-kernel-ps command

    (gdb) kdump-kernel-ps
    UID        PID        PPID       LWP        COMM                      ADDRESS
    0          0          0          0          [swapper/0]               0xffffffff8b612840
    0          1          0          1          init                      0xffffa08dff9b8000
    0          2          0          2          [kthreadd]                0xffffa08dff9b8c00
    0          3          2          3          [rcu_gp]                  0xffffa08dff9b9800
    0          4          2          4          [rcu_par_gp]              0xffffa08dff9ba400
    0          5          2          5          [kworker/0:0]             0xffffa08dff9bb000
    <snip>
    0          350        1          350        getty                     0xffffa08debe86c00
    0          385        349        385        getty                     0xffffa08dff371800
    0          386        348        386        sh                        0xffffa08dff088c00

Once you know the PID of the process you want to debug run the kdump-save-process-json
command to create process json file:

    (gdb) kdump-save-process-json process-386.json 386

After that exit from both kdump-gdbserver and gdb. Restart kdump-gdbserver and
provide the json file that was generated with -j command line option:

    $ kdump-gdbserver -f vmcore -j process-386.json
    Waiting for incoming connection on localhost port 1234
    In gdb execute the following command(s) to connect:
    # If you use PIE executable use the following command to correctly
    # load process symbols
    file <executable> -o 0x41e000
    target remote localhost:1234

    Waiting for incoming connection on localhost port 1234
    In gdb execute the following command(s) to connect:
    # If you use PIE executable use the following command to correctly
    # load process symbols
    file <executable> -o 0x41e000
    target remote localhost:1234

Now, you can continue inspecting state of the process as one would use gdb
connected to gdbserver attached to given process pid.

    $ gdb
    <snip>
    (gdb) file bash
    Reading symbols from bash...
    (gdb) set sysroot sysroot
    (gdb) target remote localhost:1234
    Remote debugging using localhost:1234
    <snip>
    Reading symbols from sysroot/lib/libc.so.6...
    Reading symbols from sysroot/lib/ld-linux-x86-64.so.2...
    Reading symbols from sysroot/lib/libnss_compat.so.2...
    0x0000003cd4cea4c3 in __GI___libc_write (fd=1, buf=0x559b10, nbytes=2) at ../sysdeps/unix/sysv/linux/write.c:26
    26	../sysdeps/unix/sysv/linux/write.c: No such file or directory.
    (gdb) bt
    #0  0x0000003cd4cea4c3 in __GI___libc_write (fd=1, buf=0x559b10, nbytes=2) at ../sysdeps/unix/sysv/linux/write.c:26
    #1  0x0000003cd4c7d835 in _IO_new_file_write (f=0x3cd4db8520 <_IO_2_1_stdout_>, data=0x559b10, n=2) at fileops.c:1176
    #2  0x0000003cd4c7cc56 in new_do_write (fp=fp@entry=0x3cd4db8520 <_IO_2_1_stdout_>, data=0x559b10 "c\n\333\324<",
        to_do=to_do@entry=2) at libioP.h:948
    #3  0x0000003cd4c7e8a9 in _IO_new_do_write (to_do=2, data=<optimized out>, fp=0x3cd4db8520 <_IO_2_1_stdout_>)
        at fileops.c:423
    #4  _IO_new_do_write (fp=fp@entry=0x3cd4db8520 <_IO_2_1_stdout_>, data=<optimized out>, to_do=2) at fileops.c:423
    #5  0x0000003cd4c7ed03 in _IO_new_file_overflow (f=0x3cd4db8520 <_IO_2_1_stdout_>, ch=10) at fileops.c:784
    #6  0x0000000000483839 in putchar (__c=10) at /usr/include/bits/stdio.h:84
    #7  echo_builtin (list=<optimized out>) at ../../bash-5.0/builtins/../../bash-5.0/builtins/echo.def:199
    #8  0x0000000000434540 in execute_builtin (builtin=builtin@entry=0x483660 <echo_builtin>, words=words@entry=0x5597c0,
        flags=flags@entry=0, subshell=subshell@entry=0) at ../bash-5.0/execute_cmd.c:4714
    #9  0x000000000043951e in execute_builtin_or_function (flags=0, fds_to_close=0x559540, redirects=<optimized out>, var=0x0,
        builtin=0x483660 <echo_builtin>, words=0x5597c0) at ../bash-5.0/execute_cmd.c:5222
    #10 execute_simple_command (fds_to_close=0x559540, async=<optimized out>, pipe_out=-1, pipe_in=-1,
        simple_command=<optimized out>) at ../bash-5.0/execute_cmd.c:4484
    #11 execute_command_internal (command=<optimized out>, asynchronous=<optimized out>, pipe_in=-1, pipe_out=<optimized out>,
        fds_to_close=0x559540) at ../bash-5.0/execute_cmd.c:844
    #12 0x0000000000439c15 in execute_command (command=0x559960) at ../bash-5.0/execute_cmd.c:394
    #13 0x000000000042160b in reader_loop () at ../bash-5.0/eval.c:175
    #14 0x00000000004204ae in main (argc=1, argv=0x7fff27982898, env=0x7fff279828a8) at ../bash-5.0/shell.c:805
    (gdb) frame 12
    #12 0x0000000000439c15 in execute_command (command=0x559960) at ../bash-5.0/execute_cmd.c:394
    394	in ../bash-5.0/execute_cmd.c
    (gdb) p *command->value.Simple->words->word
    $8 = {word = 0x5597a0 "echo", flags = 0}
    (gdb) p *command->value.Simple->words->next->word
    $9 = {word = 0x559920 "\"c\"", flags = 2}

Note if you did not compile the process with PIE do NOT use -o when executing
file command in gdb. If you do the symbols won't be loaded correctly. You can
find whether your executable is built with PIE or not with 'file executable'
command. If it says ELF file is 'executable', then it is not PIE. If it says
ELF 'shared object' it is PIE built executable and -o must be used. With
regular gdbserver and PIE executable, gdbsever during run-time reads content of
/proc/pid/maps file and determine executable load address, in kdump-gdbserver
gdb protocol remote file read is not supported. In above example bash is not
PIE so -o option was not used.

Note you need to setup the proper environment to load symbols as one would do
for a regular process core file, i.e like in the above example cross
compilation was used and one need to execute 'set sysroot' command to point
to target symbols.

Supported CPU Architectures
---------------------------

kdump-gdbserver supports x86_64 and aarch64 CPU architectures. To add a new
CPU architecture one needs to make sure that libkdumpfile supports it, and
small CPU arch specific code needs to be added in a few places.

Rational
--------

Why does one need another tool to inspect kernel vmcore files? Here are the
reasons that prompted development of kdump-gdbserver tool:

1. [gdb](https://www.gnu.org/software/gdb/)
On many CPU architectures only directly mapped memory can be inspected
with vanilla gdb, from a given vmcore file if it is captured in the ELF format,
i.e gdb is not aware of the kernel page table and cannot easily look at memory
that goes through kernel page table translation. And gdb does not understand
compressed kdump file format.

2. [crash](https://github.com/crash-utility/crash.git)
is a variant of gdb where code translating kernel virtual addresses into
physical addresses in vmcore was developed. It adds more functionality, but at
time of writing gdb version on which crash tool is based is quite old and
it does not support python scripting in gdb.

3. [crash-python](https://github.com/crash-python/crash-python)
tools that utilizes the same libkdumpfile library does understand
kernel virtual memory, it does present kernel tasks as threads as
kdump-gdbserver kernel with tasks mode does. Also similar to crash tool many
useful command are provided by the tool. But the tool depends on a modified
version of gdb
[gdb-python](https://github.com/crash-python/gdb-python)
where additional gdb python functionality is added. At time of writing
gdb-python is based on gdb-9.2.x. Without upstreaming those patches into
mainstream gdb there is a risk that version of underlying gdb of gdb-python
would be stuck in the past similar to crash tool stuck on old gdb version.

kdump-gdbserver uses gdb remote protocol between the tool and gdb. It should
continue to work with future versions of gdb, so effectively the tool is
independent from gdb version.

Also kdump-gdbserver source code is very small. It contains the bare minimum
gdb protocol implementation, naturally just the state reading part. Most of
the magic, reading vmcore file, translating virtual to physical addresses,
VMCOREINFO note access is all done by libkdumpfile library. So mapping gdb
protocol to proper libkdumpfile was not a big deal.

Note additional functionality to easily inspect kernel state could be added as
gdb python commands, and those would work with kdump-gdbserver and live kernel
gdb sessions in the same way.

Finally, kdump-gdbserver tool supports process view where state of the
user-land process can be inspected with gdb from given vmcore file if user
pages are present.

TODO
----

- Support 32bit user-land process
- Support more CPU architectures
