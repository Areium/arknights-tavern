#!/usr/bin/env python3
"""从 Ark-Models 导入角色/敌人 spine 到 data/characters/<名>/spine/<variant>/Front|Back/。

命名转换：Ark-Models 的 build_char_<key>.{atlas,png,skel} → <variant>.{atlas,png,skel}
其中 variant 是前端 SPINE_VARIANT / ENEMY_SPINE_VARIANT 的值（char_ 前缀，# → _）。
Front 与 Back 共用同一套 skel（敌人用 Back 后由前端水平翻转）。

敌人来源为 Ark-Models 的 models_enemies/（模型自带 Idle/Attack/Die/Move 战斗动画）。
"""
import os
import subprocess
import sys

ARK_REPO = os.path.join("assets", "_ark_models_tmp")
DEST = os.path.join("data", "characters")

# 中文名 → (Ark-Models key, 前端 variant 名)
MAPPING = {
    "临光": ("148_nearl", "char_148_nearl"),
    "佐菲娅": ("265_sophia", "char_265_sophia"),
    "德克萨斯": ("1028_texas2", "char_1028_texas2"),
    "玛恩纳·临光": ("4064_mlynar", "char_4064_mlynar"),
    "瑕光": ("423_blemsh", "char_423_blemsh"),
    "砾": ("237_gravel", "char_237_gravel"),
    "银灰": ("172_svrash_ambiencesynesthesia#4", "char_172_svrash_ambienceSynesthesia_4"),
    "闪灵": ("147_shining", "char_147_shining"),
    "阿米娅": ("002_amiya_epoque#4", "char_002_amiya_epoque_4"),
    "陈": ("010_chen", "char_010_chen"),
}

# 敌人：中文名 → (Ark-Models models_enemies key, 前端 variant 名)
ENEMY_MAPPING = {
    "整合运动士兵": ("1002_nsabr", "enemy_1002_nsabr"),
    "整合运动术师": ("1011_wizard", "enemy_1011_wizard"),
    "整合运动狙击手": ("1003_ncbow", "enemy_1003_ncbow"),
    "整合运动盾卫": ("1006_shield", "enemy_1006_shield"),
    "冰原战士": ("1189_krgaxe", "enemy_1189_krgaxe"),
    "冰原猎人": ("1190_krgbow", "enemy_1190_krgbow"),
    "冰原术师": ("1192_krgscr", "enemy_1192_krgscr"),
    "冰原狂战士": ("1193_krgbsk", "enemy_1193_krgbsk"),
    "山雪鬼": ("1194_krgmtr", "enemy_1194_krgmtr"),
    "山雪鬼队长": ("1194_krgmtr_2", "enemy_1194_krgmtr_2"),
    "雪原爪兽": ("1187_krghd", "enemy_1187_krghd"),
}


def git_show(relpath: str) -> bytes:
    r = subprocess.run(
        ["git", "-C", ARK_REPO, "show", f"HEAD:{relpath}"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git show 失败: {relpath}")
    return r.stdout


def get_prefix(src_dir: str, ark_key: str) -> str:
    """从 Ark-Models 目录里动态获取 build_ 开头的文件前缀（避免大小写不一致）。"""
    r = subprocess.run(
        ["git", "-C", ARK_REPO, "ls-tree", "-r", "--name-only", f"HEAD:{src_dir}/{ark_key}"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ls-tree 失败: {ark_key}")
    for name in r.stdout.decode("utf-8", errors="replace").split():
        if name.endswith(".skel"):
            return name[: -len(".skel")]
    raise RuntimeError(f"目录中找不到 .skel: {ark_key}")


def import_one(src_dir: str, cn: str, ark_key: str, variant: str) -> None:
    prefix = get_prefix(src_dir, ark_key)
    for ext in (".atlas", ".png", ".skel"):
        rel = f"{src_dir}/{ark_key}/{prefix}{ext}"
        data = git_show(rel)
        if ext == ".atlas":
            text = data.decode("utf-8", errors="replace")
            text = text.replace(f"{prefix}.png", f"{variant}.png")
            data = text.encode("utf-8")
        for d in ("Front", "Back"):
            outdir = os.path.join(DEST, cn, "spine", variant, d)
            os.makedirs(outdir, exist_ok=True)
            with open(os.path.join(outdir, f"{variant}{ext}"), "wb") as f:
                f.write(data)


def main():
    """用法: python tools/import_spine.py [enemies|operators|all]（默认 enemies）"""
    group = sys.argv[1] if len(sys.argv) > 1 else "enemies"
    jobs = []
    if group in ("operators", "all"):
        jobs += [("models", cn, key, var) for cn, (key, var) in MAPPING.items()]
    if group in ("enemies", "all"):
        jobs += [("models_enemies", cn, key, var) for cn, (key, var) in ENEMY_MAPPING.items()]
    if not jobs:
        print(f"未知分组: {group}（可选 enemies / operators / all）")
        return

    ok = 0
    fail = 0
    for src_dir, cn, ark_key, variant in jobs:
        try:
            import_one(src_dir, cn, ark_key, variant)
            print(f"OK {cn} -> {variant}")
            ok += 1
        except Exception as e:
            print(f"FAIL {cn}: {e}")
            fail += 1
    print(f"\n完成: {ok} 成功, {fail} 失败")


if __name__ == "__main__":
    main()
