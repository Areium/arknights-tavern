from GameAgent import GameAgent
from ui import OptionsMenu
from logging_setup import setup_logging, run_with_timer, get_log_path


def main():

    # 初始化日志系统（写入文件，不输出到控制台）
    log_path = setup_logging()
    print(f"欢迎使用角色扮演代理！输入 'exit' 结束对话。\n")
    print(f"调试日志: {log_path}\n")

    # 初始化代理
    agent = GameAgent()

    while True:
        # 生成对话选项（有角色时角色相关，无角色时系统菜单）
        options = agent.generate_options()
        if options:
            user_input = OptionsMenu(options).run()
        else:
            # LLM 生成失败，回退到普通输入
            user_input = input("\n你: ")

        if user_input.lower() == "exit":
            print("结束对话。")
            break

        # 运行代理并获取响应（带实时计时）
        response = run_with_timer(agent.run, user_input, 10)
        print(f"\n{response}\n")


if __name__ == "__main__":
    main()
