"""
Cards blueprint — CRUD API for character and class card JSON files.

Endpoints:
  GET  /api/cards/tree                       — tree view (characters + classes)
  GET  /api/cards                            — list characters with combat.json
  GET  /api/cards/classes                    — list classes with cards.json
  GET  /api/cards/<character_name>           — read character combat.json
  PUT  /api/cards/<character_name>           — save character combat.json
  POST /api/cards/<character_name>/cards     — create a new card for character
  DELETE /api/cards/<character_name>/cards/<card_id> — delete a card from character
  GET  /api/cards/classes/<class_name>        — read class cards.json
  PUT  /api/cards/classes/<class_name>        — save class cards.json
  POST /api/cards/classes/<class_name>/cards  — create a new card for class
  DELETE /api/cards/classes/<class_name>/cards/<card_id> — delete a card from class
"""

import hashlib
import json
import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHAR_DIR = PROJECT_ROOT / "data" / "characters"
CLASS_DIR = PROJECT_ROOT / "data" / "classes"


def _compute_hash(data: dict) -> str:
    """Compute a SHA-256 hash of card data (excluding _hash field)."""
    payload = {k: v for k, v in data.items() if k != "_hash"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ── Routes ──────────────────────────────────────────────────────────────────

def register(app, managers):
    bp = Blueprint("cards", __name__)

    @bp.route("/api/cards/classes/<class_name>", methods=["GET"])
    def get_class_cards(class_name: str):
        """Get a class's card pool."""
        path = CLASS_DIR / class_name / "cards.json"
        if not path.exists():
            return json_error(f"Class cards not found: {class_name}", 404)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            logger.error("Failed to read class cards %s: %s", class_name, e)
            return json_error(f"Failed to read class cards: {e}", 500)

    @bp.route("/api/cards/classes/<class_name>", methods=["PUT"])
    def save_class_cards(class_name: str):
        """Save a class's card pool with hash-based conflict detection."""
        data = request.json or {}
        expected_hash = data.get("_hash", "")

        path = CLASS_DIR / class_name / "cards.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
            current_hash = current.get("_hash", "")
            if expected_hash and expected_hash != current_hash:
                return json_error(
                    "Save conflict: file has been modified by another process. "
                    "Please refresh and try again.",
                    409,
                )

        # Update hash
        data["_hash"] = _compute_hash(data)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({"_hash": data["_hash"], "path": str(path)})
        except Exception as e:
            logger.error("Failed to save class cards %s: %s", class_name, e)
            return json_error(f"Failed to save class cards: {e}", 500)

    @bp.route("/api/cards/<character_name>", methods=["GET"])
    def get_character_cards(character_name: str):
        """Get a character's combat.json."""
        path = CHAR_DIR / character_name / "combat.json"
        if not path.exists():
            return json_error(f"Character cards not found: {character_name}", 404)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            logger.error("Failed to read character cards %s: %s", character_name, e)
            return json_error(f"Failed to read character cards: {e}", 500)

    @bp.route("/api/cards/<character_name>", methods=["PUT"])
    def save_character_cards(character_name: str):
        """Save a character's combat.json with hash-based conflict detection."""
        data = request.json or {}
        expected_hash = data.get("_hash", "")

        path = CHAR_DIR / character_name / "combat.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
            current_hash = current.get("_hash", "")
            if expected_hash and expected_hash != current_hash:
                return json_error(
                    "Save conflict: file has been modified by another process. "
                    "Please refresh and try again.",
                    409,
                )

        # Update hash
        data["_hash"] = _compute_hash(data)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({"_hash": data["_hash"], "path": str(path)})
        except Exception as e:
            logger.error("Failed to save character cards %s: %s", character_name, e)
            return json_error(f"Failed to save character cards: {e}", 500)

    @bp.route("/api/cards", methods=["GET"])
    def list_characters_with_cards():
        """List all characters that have combat.json."""
        chars = []
        if CHAR_DIR.exists():
            for name in sorted(os.listdir(str(CHAR_DIR))):
                subdir = CHAR_DIR / name
                if subdir.is_dir() and (subdir / "combat.json").exists():
                    chars.append(name)
        return jsonify({"characters": chars})

    @bp.route("/api/cards/classes", methods=["GET"])
    def list_classes_with_cards():
        """List all classes that have cards.json."""
        classes = []
        if CLASS_DIR.exists():
            for name in sorted(os.listdir(str(CLASS_DIR))):
                subdir = CLASS_DIR / name
                if subdir.is_dir() and (subdir / "cards.json").exists():
                    classes.append(name)
        return jsonify({"classes": classes})

    @bp.route("/api/cards/tree", methods=["GET"])
    def cards_tree():
        """Return tree structure for the card management UI."""
        characters = []
        classes = []
        character_class_map = {}

        if CHAR_DIR.exists():
            for name in sorted(os.listdir(str(CHAR_DIR))):
                subdir = CHAR_DIR / name
                if subdir.is_dir() and (subdir / "combat.json").exists():
                    characters.append(name)
                    try:
                        with open(subdir / "combat.json", "r", encoding="utf-8") as f:
                            data = json.load(f)
                        character_class_map[name] = data.get("class_name", "")
                    except Exception:
                        character_class_map[name] = ""

        if CLASS_DIR.exists():
            for name in sorted(os.listdir(str(CLASS_DIR))):
                subdir = CLASS_DIR / name
                if subdir.is_dir() and (subdir / "cards.json").exists():
                    classes.append(name)

        return jsonify({
            "characters": characters,
            "classes": classes,
            "character_class_map": character_class_map,
        })

    # ── Single-card operations (character) ──

    @bp.route("/api/cards/<character_name>/cards", methods=["POST"])
    def create_character_card(character_name: str):
        """Create a new card for a character's combat.json."""
        path = CHAR_DIR / character_name / "combat.json"
        if not path.exists():
            return json_error(f"Character cards not found: {character_name}", 404)

        new_card = request.json or {}
        if not new_card.get("card_id"):
            return json_error("card_id is required", 400)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        category = new_card.get("category", "exclusive")
        if category == "class":
            data.setdefault("class_cards", []).append(new_card)
        else:
            data.setdefault("exclusive_cards", []).append(new_card)

        data["_hash"] = _compute_hash(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "created", "card_id": new_card["card_id"], "_hash": data["_hash"]})

    @bp.route("/api/cards/<character_name>/cards/<card_id>", methods=["DELETE"])
    def delete_character_card(character_name: str, card_id: str):
        """Delete a single card from a character's combat.json."""
        path = CHAR_DIR / character_name / "combat.json"
        if not path.exists():
            return json_error(f"Character cards not found: {character_name}", 404)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        found = False
        for key in ("exclusive_cards", "class_cards"):
            cards = data.get(key, [])
            for i, card in enumerate(cards):
                if card.get("card_id") == card_id:
                    cards.pop(i)
                    found = True
                    break
            if found:
                break

        if not found:
            return json_error(f"Card not found: {card_id}", 404)

        data["_hash"] = _compute_hash(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "deleted", "card_id": card_id, "_hash": data["_hash"]})

    # ── Single-card operations (class) ──

    @bp.route("/api/cards/classes/<class_name>/cards", methods=["POST"])
    def create_class_card(class_name: str):
        """Create a new card for a class's cards.json."""
        path = CLASS_DIR / class_name / "cards.json"
        if not path.exists():
            return json_error(f"Class cards not found: {class_name}", 404)

        new_card = request.json or {}
        if not new_card.get("card_id"):
            return json_error("card_id is required", 400)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("cards", []).append(new_card)
        data["_hash"] = _compute_hash(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "created", "card_id": new_card["card_id"], "_hash": data["_hash"]})

    @bp.route("/api/cards/classes/<class_name>/cards/<card_id>", methods=["DELETE"])
    def delete_class_card(class_name: str, card_id: str):
        """Delete a single card from a class's cards.json."""
        path = CLASS_DIR / class_name / "cards.json"
        if not path.exists():
            return json_error(f"Class cards not found: {class_name}", 404)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cards = data.get("cards", [])
        found = False
        for i, card in enumerate(cards):
            if card.get("card_id") == card_id:
                cards.pop(i)
                found = True
                break

        if not found:
            return json_error(f"Card not found: {card_id}", 404)

        data["_hash"] = _compute_hash(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "deleted", "card_id": card_id, "_hash": data["_hash"]})

    app.register_blueprint(bp)
    return bp
