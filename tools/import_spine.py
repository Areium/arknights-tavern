#!/usr/bin/env python3
"""从 Ark-Models 导入角色 spine 到 data/characters/<名>/spine/<variant>/Front|Back/。

命名转换：Ark-Models 的 build_char_<key>.{atlas,png,skel} → <variant>.{atlas,png,skel}
其中 variant 是前端 SPINE_VARIANT 的值（char_ 前缀，# → _）。
Front 与 Back 共用同一套 skel（敌人用 Back 后由前端水平翻转）。
"""
import os
import subprocess

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


def git_show(relpath: str) -> bytes:
    r = subprocess.run(
        ["git", "-C", ARK_REPO, "show", f"HEAD:{relpath}"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git show 失败: {relpath}")
    return r.stdout


def get_prefix(ark_key: str) -> str:
    """从 Ark-Models 目录里动态获取 build_ 开头的文件前缀（避免大小写不一致）。"""
    r = subprocess.run(
        ["git", "-C", ARK_REPO, "ls-tree", "-r", "--name-only", f"HEAD:models/{ark_key}"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ls-tree 失败: {ark_key}")
    for name in r.stdout.decode("utf-8", errors="replace").split():
        if name.endswith(".skel"):
            return name[: -len(".skel")]
    raise RuntimeError(f"目录中找不到 .skel: {ark_key}")


def main():
    ok = 0
    fail = 0
    for cn, (ark_key, variant) in MAPPING.items():
        try:
            prefix = get_prefix(ark_key)
            for ext in (".atlas", ".png", ".skel"):
                rel = f"models/{ark_key}/{prefix}{ext}"
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
            print(f"OK {cn} -> {variant}")
            ok += 1
        except Exception as e:
            print(f"FAIL {cn}: {e}")
            fail += 1
    print(f"\n完成: {ok} 成功, {fail} 失败")


if __name__ == "__main__":
    main()
