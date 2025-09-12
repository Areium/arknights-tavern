from GameAgent import GameAgent


def main():

    # 初始化代理
    agent = GameAgent()

    print("欢迎使用角色扮演代理！输入 'exit' 结束对话。")

    while True:
        user_input = input("你: ")
        if user_input.lower() == "exit":
            print("结束对话。")
            break

        # 运行代理并获取响应
        response = agent.run(user_input, 10)
        print(f"{response}")


if __name__ == "__main__":
    main()
