# Tools
./src/agents/tools
## Read_Config
功能：告诉 Agent 某个配置是否开启，因为内核中许多结构体和函数的实现依赖于配置
实现：读取内核配置文件(.config)，并维护一个dict，存入开启的配置
## Read File
功能：读取指定目录的文件，可以指定行数
实现：open->readline
## Gdb Command
功能：读取Kdump和内核镜像信息等
实现：kdump-gdbserver
## Agent
功能：Agent可以调用子Agent来完成指定任务，并能进行多轮对话。
实现：create_agent
备注：应该限制子Agent的数量和token？
## WebSearch
功能：获取指定url的页面或搜索指定关键词
实现：爬虫。
备注：如果可能的话，后续应转变为langchain官方实现。
## CodeQuery
功能：获取指定函数定义、结构体定义、全局变量定义等
实现：codeQuery，直接使用BUGLENS的源码
备注：查看源码后发现并不精准，例如内核中函数定义可能依赖于架构、内核配置等。所以codeQuery会找到多种函数定义，源代码中直接取最后一种函数定义。感觉可以通过内核镜像锁定准确的函数定义、结构体定义等。例如可以先通过 `addr2line -a funName -e vmlinux` 获取函数在源码中的位置，然后提取出来。

# TODO
1.对工具进行测试(编写测试代码)
2.根据备注改善工具的准确性
3.进行测试，来修正或添加工具
