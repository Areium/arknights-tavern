/**
 * Spine 动画规格 — 把角色的战斗变体 skel 动画名解析为统一动作。
 *
 * 战斗变体（如 char_002_amiya/char_002_amiya_test_1）的动画名带角色专属后缀
 * （IdleM / AttackTO / DieLK），且攻击可能是多段链（Attack_Begin→Attack→Attack_End）。
 * 这里用「前缀匹配 + 多段链识别」把任意变体归一为 AnimSpec。
 *
 * 玛恩纳·临光无 Attack 动画，用 Skill_1_Start→Loop→End 链兜底。
 */

export interface AnimSpec {
  idle: string;
  start?: string;
  /** 攻击动画链（顺序播放，末段结束回 idle） */
  attack: string[];
  die: string;
}

/**
 * 从某变体的实际动画名列表解析出 AnimSpec。
 * 找不到的攻击/死亡动画返回空串，调用方需判空。
 */
export function resolveAnimSpec(animNames: string[]): AnimSpec {
  const find = (re: RegExp) => animNames.find((n) => re.test(n));

  const idle = find(/^idle/i) ?? find(/^default/i) ?? animNames[0] ?? "";

  // ── 攻击多段链识别 ──
  const atks = animNames.filter((n) => /^attack/i.test(n));
  const core = atks.slice().sort((a, b) => a.length - b.length)[0]; // 最短 = 裸 Attack
  const begin = atks.find((n) => /_begin/i.test(n));
  const end = atks.find((n) => /_end/i.test(n));
  const start = atks.find((n) => /_start/i.test(n));
  const loop = atks.find((n) => /_loop/i.test(n));
  const pre = atks.find((n) => /_pre/i.test(n));

  let attack: string[] = [];
  if (begin && core && end) attack = [begin, core, end];
  else if (start && loop && end) attack = [start, loop, end];
  else if (pre && core && end) attack = [pre, core, end];
  else if (core) attack = [core];

  // 无 Attack → Skill 兜底（玛恩纳：Skill_1_Start/Loop/End）
  if (attack.length === 0) {
    const s1s = find(/^skill_1_start/i);
    const s1l = find(/^skill_1_loop/i);
    const s1e = find(/^skill_1_end/i);
    if (s1s && s1l && s1e) attack = [s1s, s1l, s1e];
    else {
      const anySkill = find(/^skill/i);
      if (anySkill) attack = [anySkill];
    }
  }

  return {
    idle,
    start: find(/^start/i),
    attack,
    die: find(/^die/i) ?? "",
  };
}
