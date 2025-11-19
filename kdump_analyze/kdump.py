from pwn import *
from pygdbmi.gdbcontroller import GdbController
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) 
from log import *
import shutil

# extend in future
crash_word = ['BUG:',
              'Oops:',
              'Kernel panic']

end_word = ["---[ end"]

temp_file = os.path.join(os.path.dirname(__file__),'temp_report.txt')

class KdumpAnalysis:
    def __init__(self,linux:str,crash:str,vmcore:str,port:int,gdb_path='gdb'):
        self.linux = linux
        
        exist, self.crash = self.checkTool(crash)
        
        self.crash_word = crash_word
        
        self.temp_file = temp_file
        
        self.crash_report = None
        
        if not exist:
            raise FileNotFoundError(f"kdump-gdbserver tool not found: {crash}")
        
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
        
        # assume tool in ./ path
        local_path = os.path.join(os.path.dirname(__file__),tool)
        
        if os.path.exists(local_path) and os.access(local_path, os.X_OK):
            return True,local_path
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
    
                    
    def execute(self,command:str):
        try:
            self.logger.info(f"execute gdb command: {command}")
            output = self.gdb.write(command)
            return self.parseOutput(output)
        except Exception as e:
            self.logger.error(f"Failed to execute gdb command: {command}, error: {e}")
            return {'result': 'error', 'output': [str(e)]}
        
        
    def loadKdump(self):
        self.logger.info("start up kdump server")
        output = ''
        try:
            self.kdump = process(f"{self.crash} -p {self.port} -f {self.vmcore}",shell=True)
            output=self.kdump.recvuntil(f"target remote localhost:{self.port}".encode(),timeout=30)
        except:
            self.logger.error("startup gdbserver failed!!")
            return False,output.decode()
        if f"target remote localhost:{self.port}".encode() not in output:
            return False,output.decode()
        else:
            return True,"startup kdump-gdbserver success"
        
    
    def loadGDB(self):
        try:
            self.gdb = GdbController([self.gdb_path, "--interpreter=mi2"])
            res = self.execute(f'target remote:{self.port}')
            if res['result'] == 'error':
                return False,res['output']
            vmlinux = os.path.join(self.linux,'vmlinux')
            if not os.path.exists(vmlinux):
                raise FileNotFoundError("vmlinux file not found")
            res = self.execute(f'file {vmlinux}')
            if res['result'] == 'error':
                return False,res['output']
            # to import linux smoothly
            script_dir = os.path.join(self.linux,'scripts','gdb')
            self.execute(f'python sys.path.insert(0, "{script_dir}")')
            script_dir = os.path.join(script_dir,'vmlinux-gdb.py')
            # load script file to lx-dmesg
            if not os.path.exists(script_dir):
                raise FileNotFoundError("vmlinux-gdb.py not found")
            res = self.execute(f'source {script_dir}')
            if res['result'] == 'error':
                return False,res['output']
            self.execute('set pagination off')
            return True,"startup gdb success"
        except:
            return False,"startup gdb faliled!!"
        
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
            filter_report = report[-100:]  # last 100 lines
        elif e_idx != -1:
            if e_idx - s_idx <= 20:
                filter_report = report[-100:]
            else:
                filter_report = report[s_idx:e_idx+1]
        else:
            filter_report = report[s_idx:-3]
            
        report.clear()
        
        # Strip time and other prefixes
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
            if exist and tool is not None:
                addr_info = self.extractAddress(line)
                if addr_info:
                    try:
                        cmd = f'{tool} -e {os.path.join(self.linux,"vmlinux")} -i -a {addr_info}'
                        addr2line_output = os.popen(cmd).read().strip()
                        # extract real file location
                        addr2line_output = addr2line_output.split('\n')[-1]
                        idx = addr2line_output.find(':')
                        file_path = addr2line_output[:idx]
                        relpath = os.path.relpath(file_path, self.linux)
                        form = relpath + addr2line_output[idx:]
                        line = line + " " + form
                    except Exception as e:
                        self.logger.error(f"Failed to run addr2line: {e}")
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
    linux = '/root/agent4kdump/kernel/linux-next-9e50b94b3eb0d859a2586b5a40d7fd6e5afd9210'
    vmcore = '/root/agent4kdump/vmcore'
    crash = '/root/agent4kdump/kdump_analyze/kdump-gdbserver/kdump-gdbserver'
    gdb_path = 'gdb'
    kdump = KdumpAnalysis(linux,crash,vmcore,1234,gdb_path)
    kdump.loadKdump()
    status,report = kdump.loadGDB()
    print(status)
    print(report)
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