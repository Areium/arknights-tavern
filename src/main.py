import sys

from GameAgent import GameAgent
from ui import OptionsMenu, stream_print, _TOGGLE_MODE, _CONTINUE
from logging_setup import setup_logging, run_with_timer, get_log_path


def main():

    # 初始化日志系统（写入文件，不输出到控制台）
    log_path = setup_logging()
    print(f"欢迎使用角色扮演代理！输入 'exit' 结束对话。\n")
    print(f"调试日志: {log_path}\n")

    # 初始化代理
    agent = GameAgent()

    while True:
        # 生成对话选项（根据当前模式）
        options = agent.generate_options()
        if options:
            user_input = OptionsMenu(
                options,
                mode=agent.dialogue_mode,
                character_name=agent.current_character_name or "",
                scene_characters=agent.scene_manager.get_scene_characters(),
            ).run()
            if user_input is None:
                print("结束对话。")
                break

            # 模式切换信号
            if user_input == _TOGGLE_MODE:
                msg = agent.toggle_mode()
                print(msg)
                continue

            # 继续推进剧情 → 转换为内部信号
            if user_input == "继续推进剧情":
                user_input = _CONTINUE
        else:
            user_input = input("\n你: ")

        if user_input.lower() == "exit":
            print("结束对话。")
            break

        # 运行代理并获取响应
        if agent.dialogue_mode == "story" and agent.current_character_agent:
            # 剧情模式：显示状态 + 流式输出
            status = agent.scene_manager.build_status(
                agent.environment.build_context(),
                agent.player_info if agent.player_loaded else None,
            )
            print(f"\n{status}\n")

            print()
            response = agent.run(user_input, max_turns=10, stream=True)
            print()
        else:
            # 系统模式：带计时，打字机输出
            response = run_with_timer(agent.run, user_input, max_turns=10)
            print()
            stream_print(response, delay=0.02)
            print()


if __name__ == "__main__":
    main()
