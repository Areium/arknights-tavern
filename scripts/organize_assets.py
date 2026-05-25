"""
Organize Arknights art assets from raw repo into per-character directories.

Usage: python scripts/organize_assets.py

Reads from: assets/ArknightsGameResource/
Writes to:  assets/organized/
"""

import os
import json
import shutil
import sys
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, 'assets', 'ArknightsGameResource')
ORG = os.path.join(BASE, 'assets', 'organized')

# Character mapping: project_name -> primary_char_id
# Each entry: (display_name, [list of char_ids (primary first)], notes)
CHARACTERS = [
    ('阿米娅',       ['char_002_amiya'],     'Amiya'),
    ('陈',           ['char_010_chen'],       "Ch'en"),
    ('临光',         ['char_148_nearl'],      'Nearl'),
    ('德克萨斯',     ['char_102_texas'],      'Texas'),
    ('银灰',         ['char_172_svrash'],     'SilverAsh'),
    ('闪灵',         ['char_147_shining'],    'Shining'),
    ('砾',           ['char_237_gravel'],     'Gravel'),
    ('瑕光',         ['char_423_blemsh'],     'Blemishine'),
    ('玛恩纳·临光', ['char_4064_mlynar'],    'Mlynar Nearl'),
    ('佐菲娅',       ['char_265_sophia'],     'Whislash'),
    ('霜星',         ['char_4093_frston'],    'FrostNova (NPC)'),
    ('博士',         ['npc_001_doctor'],      'Doctor (Player character)'),
]

# Asset type descriptions for index.json
SKIN_MEANING = {
    '_1':   ' Elite 0 / Elite 1 (default)',
    '_2':   ' Elite 2',
    '_1+':  ' Elite 1 alternate',
    '_epoque':  ' Epoque series skin',
    '_winter':  ' Winter series skin',
    '_summer':  ' Summer series skin',
    '_sale':    ' Sale/Brand skin',
    '_witch':   ' Halloween/Witch skin',
    '_nian':    ' Chinese New Year skin',
    '_boc':     ' BoC series skin',
    '_iteration':   ' Iteration skin',
    '_ambiencesynesthesia': ' Ambience Synesthesia skin',
    '_snow':    ' Snow series skin',
    '_test':    ' Test/placeholder',
    '_rainbow6':    ' Rainbow6 collab skin',
}


def get_skin_label(filename):
    """Extract human-readable skin label from filename."""
    base = filename.replace('.png', '')
    for code, label in SKIN_MEANING.items():
        if code in base:
            return label.strip()
    return ''


def is_default_variant(fname):
    """Check if this is the default (E0/E1) variant."""
    parts = fname.replace('.png', '').split('_')
    last = parts[-1]
    return last == '1' or last == '1+' or (last.endswith('b') and parts[-2] == '1')


def organize_character(name, char_ids, raw, org):
    """Copy and organize assets for one character."""
    char_dir = os.path.join(org, 'characters', name)
    os.makedirs(char_dir, exist_ok=True)

    portraits = []
    skins = []
    avatars = []

    for cid in char_ids:
        # Collect portraits
        raw_portrait_dir = os.path.join(raw, 'portrait')
        if os.path.isdir(raw_portrait_dir):
            for f in sorted(os.listdir(raw_portrait_dir)):
                if f.startswith(cid):
                    portraits.append(f)

        # Collect full-body skins
        raw_skin_dir = os.path.join(raw, 'skin')
        if os.path.isdir(raw_skin_dir):
            for f in sorted(os.listdir(raw_skin_dir)):
                if f.startswith(cid):
                    skins.append(f)

        # Collect avatars
        raw_avatar_dir = os.path.join(raw, 'avatar')
        if os.path.isdir(raw_avatar_dir):
            for f in sorted(os.listdir(raw_avatar_dir)):
                if f.startswith(cid):
                    avatars.append(f)

    # Copy portrait files
    if portraits:
        port_dir = os.path.join(char_dir, 'portrait')
        os.makedirs(port_dir, exist_ok=True)
        for f in portraits:
            src = os.path.join(raw, 'portrait', f)
            dst = os.path.join(port_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
        print(f'  Portraits: {len(portraits)} files')

    # Copy skin files
    if skins:
        skin_dir = os.path.join(char_dir, 'skin')
        os.makedirs(skin_dir, exist_ok=True)
        for f in skins:
            src = os.path.join(raw, 'skin', f)
            dst = os.path.join(skin_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
        print(f'  Skins: {len(skins)} files')

    # Copy avatar files
    if avatars:
        ava_dir = os.path.join(char_dir, 'avatar')
        os.makedirs(ava_dir, exist_ok=True)
        for f in avatars:
            src = os.path.join(raw, 'avatar', f)
            dst = os.path.join(ava_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
        print(f'  Avatars: {len(avatars)} files')

    return {
        'name': name,
        'char_ids': char_ids,
        'portraits': portraits,
        'skins': skins,
        'avatars': avatars,
        'default_portrait': next((p for p in portraits if is_default_variant(p)), portraits[0] if portraits else None),
        'default_skin': next((s for s in skins if is_default_variant(s)), skins[0] if skins else None),
        'default_avatar': next((a for a in avatars if is_default_variant(a)), avatars[0] if avatars else None),
    }


def organize_class_icons(raw, org):
    """Copy class icons from item/ directory (class-related icons)."""
    cls_dir = os.path.join(org, 'icons', 'classes')
    os.makedirs(cls_dir, exist_ok=True)

    # Class icons in Arknights are in item/ with patterns like:
    # class_<name>.png, icon_<name>.png
    raw_item = os.path.join(raw, 'item')
    copied = 0
    if os.path.isdir(raw_item):
        class_patterns = ['class_', 'icon_profession_', 'icon_class_']
        for f in sorted(os.listdir(raw_item)):
            for pat in class_patterns:
                if f.startswith(pat):
                    src = os.path.join(raw_item, f)
                    dst = os.path.join(cls_dir, f)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                    copied += 1
                    break
    print(f'  Class icons: {copied} files')
    return copied


def organize_skill_icons(raw, org):
    """Copy skill icons."""
    sk_dir = os.path.join(org, 'icons', 'skills')
    os.makedirs(sk_dir, exist_ok=True)

    raw_skill = os.path.join(raw, 'skill')
    copied = 0
    if os.path.isdir(raw_skill):
        for f in sorted(os.listdir(raw_skill)):
            src = os.path.join(raw_skill, f)
            dst = os.path.join(sk_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            copied += 1
    print(f'  Skill icons: {copied} files')
    return copied


def organize_item_icons(raw, org):
    """Copy a selection of item icons (only commonly used)."""
    item_dir = os.path.join(org, 'icons', 'items')
    os.makedirs(item_dir, exist_ok=True)

    raw_item = os.path.join(raw, 'item')
    copied = 0
    if os.path.isdir(raw_item):
        # Common item types to include
        common = ['MTL', 'EXP', 'AP', 'coin', 'gold', '3003', '3004', '4001',
                   'originium', 'orundum', 'recruit', 'permit']
        for f in sorted(os.listdir(raw_item)):
            include = any(c in f for c in common)
            if include:
                src = os.path.join(raw_item, f)
                dst = os.path.join(item_dir, f)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                copied += 1
    print(f'  Item icons: {copied} files (filtered)')
    return copied


def organize_backgrounds(raw, org):
    """Copy battle map backgrounds (from map/ - these are tactical map previews).

    Note: True dialogue backgrounds (avg_bg) are NOT in this repo.
    They exist in fexli/ArknightsResource under avgs/.
    """
    bg_dir = os.path.join(org, 'backgrounds')
    os.makedirs(bg_dir, exist_ok=True)

    raw_map = os.path.join(raw, 'map')
    copied = 0
    if os.path.isdir(raw_map):
        for f in sorted(os.listdir(raw_map)):
            src = os.path.join(raw_map, f)
            dst = os.path.join(bg_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            copied += 1
    print(f'  Map backgrounds: {copied} files')
    return copied


def main():
    print("=== Organizing Arknights Art Assets ===\n")

    # Verify raw repo exists
    if not os.path.isdir(RAW):
        print(f"ERROR: Raw repo not found at {RAW}")
        print("Please clone yuanyan3060/ArknightsGameResource into assets/ArknightsGameResource/")
        sys.exit(1)

    index = {
        'source': 'yuanyan3060/ArknightsGameResource',
        'characters': {},
        'icons': {},
        'backgrounds': {},
    }

    # Organize characters
    print("--- Characters ---")
    for name, char_ids, _ in CHARACTERS:
        print(f"\n{name} ({', '.join(char_ids)}):")
        info = organize_character(name, char_ids, RAW, ORG)
        index['characters'][name] = info

    # Organize icons
    print("\n\n--- Icons ---")
    index['icons']['classes'] = organize_class_icons(RAW, ORG)
    index['icons']['skills'] = organize_skill_icons(RAW, ORG)
    index['icons']['items'] = organize_item_icons(RAW, ORG)

    # Organize backgrounds
    print("\n--- Backgrounds ---")
    index['backgrounds']['maps'] = organize_backgrounds(RAW, ORG)

    # Write index.json
    index_path = os.path.join(ORG, 'index.json')
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f'\nIndex written to {index_path}')

    # Summary
    total = sum(
        len(info['portraits']) + len(info['skins']) + len(info['avatars'])
        for info in index['characters'].values()
    )
    print(f'\n=== Done ===')
    print(f'Characters: {len(index["characters"])}')
    print(f'Total assets: {total}')
    print(f'Output: {ORG}')


if __name__ == '__main__':
    main()
