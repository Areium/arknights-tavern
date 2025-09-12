import os
import frontmatter
from flask import Flask, jsonify, request
from flask_cors import CORS
from GameAgent import GameAgent

app = Flask(__name__)
CORS(app)  # 允许所有来源的跨域请求，方便开发

# 全局变量，用于存储每个角色的 Agent 实例
agents = {}
# 角色数据的基础路径
character_data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'characters'))

def get_character_list_data():
    """扫描角色数据目录并返回角色列表数据。"""
    try:
        files = [f for f in os.listdir(character_data_path) if f.endswith('.md')]
        characters = []
        for f in files:
            char_id = os.path.splitext(f)[0]
            with open(os.path.join(character_data_path, f), "r", encoding="utf-8") as char_file:
                metadata = frontmatter.load(char_file).metadata
                char_name = metadata.get("name", char_id)
            characters.append({"id": char_id, "name": char_name})
        return characters
    except Exception as e:
        # 在服务器日志中记录错误
        app.logger.error(f"Failed to load characters: {str(e)}")
        return None

@app.route('/api/characters', methods=['GET'])
def get_characters():
    """API 端点：获取角色列表。"""
    characters = get_character_list_data()
    if characters is not None:
        return jsonify(characters)
    return jsonify({"error": "Could not load characters"}), 500

@app.route('/api/characters/<string:character_id>', methods=['GET'])
def get_character_config(character_id):
    """API 端点：获取指定角色的配置。"""
    try:
        file_path = os.path.join(character_data_path, f"{character_id}.md")
        if not os.path.isfile(file_path):
            return jsonify({"error": "Character not found"}), 404
            
        with open(file_path, "r", encoding="utf-8") as f:
            character_data = frontmatter.load(f)
        return jsonify({"metadata": character_data.metadata, "content": character_data.content})
    except Exception as e:
        app.logger.error(f"Failed to load config for {character_id}: {str(e)}")
        return jsonify({"error": f"Could not load config for {character_id}"}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """API 端点：处理聊天请求。"""
    data = request.json
    char_id = data.get("character_id")
    user_input = data.get("input")

    if not char_id or user_input is None:
        return jsonify({"error": "character_id and input are required"}), 400

    if char_id not in agents:
        agents[char_id] = GameAgent(char_id)
    
    agent = agents[char_id]
    response = agent.run(user_input, stream=False)
    return jsonify({"response": response})

@app.route('/api/reset', methods=['POST'])
def reset_chat():
    """API 端点：重置指定角色的对话历史。"""
    data = request.json
    char_id = data.get("character_id")

    if not char_id:
        return jsonify({"error": "character_id is required"}), 400

    if char_id in agents:
        # 通过重新初始化 Agent 来清空历史记录
        agents[char_id] = GameAgent(char_id)
        return jsonify({"message": f"Chat history for {char_id} has been reset."})
    
    return jsonify({"message": "No active session to reset."}) # 即使没有会话也返回成功

if __name__ == '__main__':
    # 默认运行在 http://127.0.0.1:5000
    app.run(debug=True)
