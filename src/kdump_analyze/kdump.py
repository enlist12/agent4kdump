from pwn import *
from pygdbmi.gdbcontroller import GdbController
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) 
from log import *
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# extend in future
crash_word = ['BUG:',
              'Oops:',
              'Kernel panic',
              'general protection fault']

end_word = ["---[ end"]

temp_file = os.path.join(os.path.dirname(__file__),'temp_report.txt')

class KdumpAnalysis:
    def __init__(self,linux:str,kdump_server:str,vmcore:str,port=1234,gdb_path='gdb'):
        self.linux = linux
        
        exist, self.kdump_server = self.checkTool(kdump_server)
        
        self.crash_word = crash_word
        
        self.temp_file = temp_file
        
        self.crash_report = None
        self.gdb = None
        self.kdump = None
        
        if not exist:
            raise FileNotFoundError(f"kdump-gdbserver tool not found: {kdump_server}")
        
        exist, self.gdb_path = self.checkTool(gdb_path)
        
        if not exist:
            raise FileNotFoundError(f"gdb tool not found: {gdb_path}")
        
        self.vmcore = vmcore
        
        if not os.path.exists(vmcore) :
            raise FileNotFoundError(f"vmcore file not found: {vmcore}")
        
        self.port = port
        
        self.logger = get_logger("kdump")
        self.logger.info("initialize kdump analysis module")
    
    @staticmethod
    def checkTool(tool:str):
        '''
        check tool existence
        return bool,path
        '''
        tool_path = shutil.which(tool)
        
        if tool_path:
            return True,tool_path
        
        # Direct Tool Path, not defined in PATH
        if not os.path.isabs(tool):
            tool_path = os.path.join(os.path.dirname(__file__),tool)
        
        if os.path.exists(tool_path) and os.access(tool_path, os.X_OK):
            return True,tool_path
        
        return False,None

        
    
    def parseOutput(self,msg:list):
        '''
        parse gdbmi output
        get type console && output
        return depend on type result
        try to record type log as debug info?
        '''
        output =  []
        result =  None
        for res in msg:
            # such as ! ls, maybe need to filter commands
            if res['type'] == 'console' and res['payload'] != None:
                output.append(res['payload'])
            elif res['type'] == 'output' and res['payload'] != None:
                output.append(res['payload'])
            elif res['type'] == 'result':
                if res['message'] == 'error':
                    output.append(res['payload']['msg'])
                    result = 'error'
                else:
                    result = 'success'
        value = {
            'result':result,
            'output':output
        }
        return value
    
                    
    def execute(self,command:str)->dict:
        try:
            # should not happen, just take a check
            if not self.gdb :
                return {'result': 'error', 'output': ['gdb is not alive']}
            self.logger.info(f"execute gdb command: {command}")
            output = self.gdb.write(command,timeout_sec=5)
            return self.parseOutput(output)
        except Exception as e:
            self.logger.error(f"Failed to execute gdb command: {command}, error: {e}")
            return {'result': 'error', 'output': [str(e)]}
        
        
    def loadKdump(self):
        self.logger.info("Initializing kdump server")
        output = ''
        try:
            self.kdump = process(f"{self.kdump_server} -p {self.port} -f {self.vmcore}",shell=True)
            output=self.kdump.recvuntil(f"target remote localhost:{self.port}".encode(),timeout=30)
        except:
            raise RuntimeError("Initialize kdump-gdbserver failed")
        if f"target remote localhost:{self.port}".encode() not in output:
            raise RuntimeError("kdump-gdbserver connect vmcore failed")
        else:
            return
        
    
    def loadGDB(self):
        self.logger.info("Initializing GDB")
        try:
            self.gdb = GdbController([self.gdb_path, "--interpreter=mi2"])
            res = self.execute(f'target remote:{self.port}')
            if res['result'] == 'error':
                raise RuntimeError("connect to kdump-gdbserver failed")
            vmlinux = os.path.join(self.linux,'vmlinux')
            if not os.path.exists(vmlinux):
                raise FileNotFoundError("vmlinux file not found")
            res = self.execute(f'file {vmlinux}')
            if res['result'] == 'error':
                raise RuntimeError("failed to load vmlinux file")
            # to import linux smoothly
            script_dir = os.path.join(self.linux,'scripts','gdb')
            self.execute(f'python sys.path.insert(0, "{script_dir}")')
            script_dir = os.path.join(script_dir,'vmlinux-gdb.py')
            # load script file to lx-dmesg
            if not os.path.exists(script_dir):
                raise FileNotFoundError("vmlinux-gdb.py not found")
            res = self.execute(f'source {script_dir}')
            if res['result'] == 'error':
                raise RuntimeError("failed to source vmlinux-gdb.py")
            self.execute('set pagination off')
            return
        except:
            raise RuntimeError("Initialize GDB failed")
        
    def extractAddress(self,text:str):
        '''
        extract address from text
        return address or None
        '''
        pattern = r'[a-zA-Z_][a-zA-Z0-9_]*\+0x[0-9a-fA-F]+(?=/0x[0-9a-fA-F]+)'
        match = re.search(pattern, text)
        return match.group(0) if match else None
        
        
    def filterCrashReport(self,report:list):
        """
        Parse crash report to extract relevant information
        Format the report just like Syzkaller
        """
        exist, tool = self.checkTool("addr2line")
        
        if not exist:
            self.logger.warning("addr2line tool not found, skip address translation")
        
        filter_report = None
        s_idx = -1
        e_idx = -1
        
        for idx,line in enumerate(report):
            if s_idx == -1:
                for word in self.crash_word:
                    if word in line:
                        s_idx = idx
            else:
                for word in end_word:
                    if word in line and s_idx != -1:
                        e_idx = idx
        
        if s_idx == -1:
            filter_report = report[-150:]  # last 150 lines
        elif e_idx != -1:
            if e_idx - s_idx <= 20:
                filter_report = report[-150:]
            else:
                filter_report = report[s_idx:e_idx+1]
        else:
            filter_report = report[s_idx:-3]
            
        report.clear()
        
        # First pass: strip prefixes and collect addresses
        processed_lines = []
        addr_tasks = []  # (line_idx, addr_info, original_line)
        
        for line in filter_report:
            line = line.strip()
            # GDB log would add \n" at the end of line
            if line.endswith('\\n"'):
                line = line[:-3]
            # Remove leading timestamp [ 1234.567890]
            if "] " in line:
                index=line.find("] ")
                line=line[index+2:]
            # Remove unreliable trace
            if line.startswith(" ?"):
                line = line[2:]
            
            processed_lines.append(line)
            
            # Collect addresses for parallel processing
            if exist and tool is not None:
                addr_info = self.extractAddress(line)
                if addr_info:
                    addr_tasks.append((len(processed_lines) - 1, addr_info))
        
        # Second pass: parallel addr2line execution
        addr_results = {}  # line_idx -> translated_info
        
        if addr_tasks and exist and tool is not None:
            def run_addr2line(task):
                line_idx, addr_info = task
                try:
                    cmd = f'{tool} -e {os.path.join(self.linux,"vmlinux")} -i -a {addr_info}'
                    addr2line_output = os.popen(cmd).read().strip()
                    # extract real file location
                    addr2line_output = addr2line_output.split('\n')[-1]
                    idx = addr2line_output.find(':')
                    if idx != -1:
                        file_path = addr2line_output[:idx]
                        relpath = os.path.relpath(file_path, self.linux)
                        form = relpath + addr2line_output[idx:]
                        return line_idx, form
                except Exception as e:
                    self.logger.error(f"Failed to run addr2line for {addr_info}: {e}")
                return line_idx, None
            
            # Use ThreadPoolExecutor for parallel execution
            max_workers = min(len(addr_tasks), 8)  # Limit to 8 threads
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(run_addr2line, task): task for task in addr_tasks}
                for future in as_completed(futures):
                    line_idx, result = future.result()
                    if result:
                        addr_results[line_idx] = result
        # Third pass: append addr2line results to lines
        for idx, line in enumerate(processed_lines):
            if idx in addr_results:
                line = line + " " + addr_results[idx]
            report.append(line)
        
        return report
    

    def getCrashReport(self):
        try:
            if self.crash_report :
                return True,self.crash_report
            #clear the file
            f = open(self.temp_file,'w')
            f.truncate(0)
            f.close()
            
            self.execute(f'set logging file {self.temp_file}')
            self.execute('set logging enabled on')
            self.execute('lx-dmesg')
            self.execute('set logging enabled off')
            
            with open(self.temp_file,'r') as f:
                report = f.readlines()
                
            report = report[:-2]
            #assume the last 100 lines are crash report
            report = self.filterCrashReport(report)
            #store crash report
            self.crash_report = '\n'.join(report)
            return True,self.crash_report
        except Exception as e:
            return False,str(e)
        
    
    def stop(self):
        try:
            self.logger.info("stop kdump analysis")
            self.gdb.exit()
            self.kdump.close()
            return True,"stop kdump analysis success"
        except:
            return False,"stop kdump analysis failed"
        
        
if __name__ == "__main__":
    linux = '/root/agent4kdump/kernel/linux-0/linux'
    vmcore = '/root/agent4kdump/case/719da9b149a931f5143f/vmcore'
    crash = '/root/agent4kdump/kdump_analyze/kdump-gdbserver/kdump-gdbserver'
    gdb_path = 'gdb'
    kdump = KdumpAnalysis(linux,crash,vmcore,1234,gdb_path)
    kdump.loadKdump()
    kdump.loadGDB()
    # test gdbmi output
    res = kdump.execute("! ls")
    print(res)
    res = kdump.execute("x/2gx 0xffffffff81000000")
    print(res)
    res = kdump.execute("info registers")
    print(res)
    # test error inst
    res = kdump.execute("x/2gx 0xzzzzzzzz")
    print(res)
    res = kdump.execute("hhhhhh")
    print(res)
    # get crash report
    status,report = kdump.getCrashReport()
    print(status)
    print(report)