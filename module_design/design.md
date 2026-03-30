首先本项目分成两部分。

一部分是search_agent
这部分Agent功能


首先是根据崩溃报告搜索相关的漏洞和报告


那么这里搜索相关的崩溃报告怎么搜？


首先根据语义，我们对崩溃报告做一个指纹提取
TODO:这里的指纹提取需要设计。比方说对于一个崩溃报告，我们应该提取里面的哪些内容能更好的相似匹配相关的内容
这里需要做一个简单的验证实验。


然后根据这个相似的指纹，选出前top个崩溃报告以及对应的fix意见和分析过程
将fix意见和analysis丢入下一个流程


另一部分是analysis_agent

这部分agent接受的输入是 last_content:
和kdump文件路径

这部分的工作流程类似于之前的污点分析：
首先我们读取输入的崩溃报告。
然后根据另外几个崩溃报告的分析过程给出当前崩溃报告的错误假设。
根据这些假设，去找直接崩溃对象，然后根据直接崩溃对象进行污点分析。
污点分析过程中如果出现条件的情况我们参考假设

然后最后进行根因总结。



那么实际上我们的两个agent实际是两个process
一个是search process
一个是analysis process
两个process 相互进行。

search process里面我不知道需要哪些agent来进行处理

这个过程首先第一个问题，我们应该如何去搜索这部分的内容？
崩溃报告究竟需要哪些部分看着一样就可以确定为相似？


既然相似过后，我又应该如何构建整个Database来pop出来那些相似的报告？
而且这些相似的报告又应该如何作用于下面的分析流程？



analysis process里面需要一个工作流

这个工作流分成

start_debug
object_analysis
taint_analysis
root_cause_analysis
四个部分
这个工作流中间的分析过程通过下面这个obj来进行传递
```python
class TaintAnalysisObj(BaseModel):
    file_name: str = Field(
        description="File containing the traced object assignment"
    )
    variable_name: str = Field(description="Variable or state object name")
    line: int = Field(description="1-based source line of the traced object")
    column: Optional[int] = Field(default=None, description="1-based column if known")
    current_function: str = Field(
        description="Function where this object is identified"
    )
    explain: str = Field(
        description="Why this object is relevant and how it propagates"
    )
    end: bool = Field(description="Whether taint tracing should stop")

    def get_prompt(self) -> str:
        col = f":{self.column}" if self.column else ""
        return f"""
        The previous taint object is `{self.variable_name}`
        in file {self.file_name} at line {self.line} column {self.column}.
        This object is in function {self.current_function}.
        Here is a short explain of it: {self.explain}
        """
```

那么接下来就是对这些节点的工具设计

start_debug 作为我们整个流程的入口，我们可以在messages里面加入
对崩溃报告本身的总结。

然后是object_analysis。这里的话我们仅仅需要根据崩溃报告解析出相应的崩溃对象

我们在这个过程中设计的工具为

read_file(filename)
上面那个仅仅用于给下面那个兜底
read_file_by_linenum(filename:str,line:int,range=10)
get_source_code(func_name|func_address,code_number)
get_source_code 通过codequery来接入  # 这里写个TODO即可。


然后通过这三个工具来完成Linux代码的查询来从头进行静态分析。

对于整个分析的process，我们用一个类来管理。

这个类里面需要维护的对象有:

首先是init的大模型
我们可以用init 两个  一个是  llm   另外一个是reasoner
然后后面根据配置自行选择每个节点使用的llm

```python
class AnalysisProcess():
    def __init__(self):
        self.llm = 
        self.reasoner = 

```
使用reasoner进行分析，使用llm进行工具调用。这是最理想的
但是现在dpsk的reasoner工具调用情况我不知道怎么样了？
# TODO： 调查这部分内容

然后是4个流程。4个流程里面的prompt建议先手写然后AI润色。  最好不要分太多点
































