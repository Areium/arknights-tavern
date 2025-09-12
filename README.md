# Role-Playing Agent

该项目是一个角色扮演代理，旨在通过与用户进行对话来模拟不同角色的互动。代理能够加载预定义的角色，并根据用户输入进行响应。

## 项目结构

```
role-playing-agent
├── src
│   ├── main.py          # 应用程序的入口点，负责初始化代理并处理用户输入
│   ├── agent.py         # 定义了 Agent 类，管理与用户的对话
│   ├── llm_loader.py    # 加载和配置本地语言模型
│   ├── tools.py         # 定义可用的工具及其功能
│   └── prompts.py       # 包含与角色进行对话的提示模板
├── data
│   └── characters
│       └── sample_character.md  # 角色的描述和背景信息
├── requirements.txt     # 列出项目所需的Python依赖项
└── README.md            # 项目的文档
```

## 安装步骤

1. 克隆此仓库到本地：
   ```
   git clone <repository-url>
   ```
2. 进入项目目录：
   ```
   cd role-playing-agent
   ```
3. 安装所需的依赖项：
   ```
   pip install -r requirements.txt
   ```

## 使用说明

1. 运行应用程序：
   ```
   python src/main.py
   ```
2. 按照提示输入您的问题或请求，代理将根据加载的角色进行响应。

## 贡献

欢迎任何形式的贡献！请提交问题或拉取请求以帮助改进此项目。