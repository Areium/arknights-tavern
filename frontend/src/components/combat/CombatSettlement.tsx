/**
 * CombatSettlement — 战斗结算面板（纯展示组件）。
 *
 * 数据来自后端结算 DTO（`CombatSettlementDTO`），本组件不做任何数值计算，
 * 只负责渲染：每角色经验/升级前后/属性变化/经验进度条、其他奖励、空状态提示。
 * 玩家点击「确认结算」后由父组件关闭面板并返回对话。
 */
import type { CombatSettlementDTO, CharacterSettlementDTO } from "../../types";

interface Props {
  settlement: CombatSettlementDTO;
  /** 正在提交结算（写回存档） */
  busy?: boolean;
  /** 写回失败的错误信息 */
  error?: string | null;
  /** 已选中的卡牌 id（战后 1 选 1） */
  pickedCardId?: string | null;
  onCardPick?: (cardId: string) => void;
  onConfirm: () => void;
  /** 写回失败后重试 */
  onRetry?: () => void;
  /** 测试战斗不写回存档，按钮文案区分 */
  isTest?: boolean;
}

function XpBar({ xp, needed, level }: { xp: number; needed: number; level: number }) {
  const pct = needed > 0 ? Math.min(100, (xp / needed) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-[10px] text-gray-500 font-mono">XP {xp} / {needed}</span>
        <span className="text-[10px] text-gray-500 font-mono">Lv.{level}</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className="h-full bg-amber-400 transition-all" style={{ width: pct + "%" }} />
      </div>
    </div>
  );
}

function CharacterRow({ ch }: { ch: CharacterSettlementDTO }) {
  const leveled = ch.level_delta > 0;
  return (
    <div className="text-left px-3 py-2.5 rounded-lg bg-gray-800/50 border border-combat-border/60">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-sm text-gray-100 font-display tracking-wide">{ch.name}</span>
        {!ch.alive && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-950/70 text-red-300 border border-red-900/60">
            阵亡
          </span>
        )}
        <span className="ml-auto text-xs font-mono text-amber-300">
          +{ch.xp_gained} XP
        </span>
      </div>

      {leveled ? (
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-xs text-gray-400 font-mono">Lv.{ch.level_before}</span>
          <span className="text-cyan-400 text-xs">→</span>
          <span className="text-sm font-bold text-combat-gold font-mono">Lv.{ch.level_after}</span>
          {ch.level_delta > 1 && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-950/70 text-amber-300 border border-amber-900/60">
              连升 {ch.level_delta} 级
            </span>
          )}
        </div>
      ) : (
        <div className="text-xs text-gray-500 font-mono mb-1.5">Lv.{ch.level_after}</div>
      )}

      {ch.attribute_changes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-1.5">
          {ch.attribute_changes.map((a) => (
            <span
              key={a.name}
              className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/50 text-emerald-300 border border-emerald-900/60 font-mono"
            >
              {a.name} {a.before} → {a.after} ({a.delta > 0 ? "+" : ""}{a.delta})
            </span>
          ))}
        </div>
      )}

      {((ch.attribute_points_gained || 0) > 0
        || (ch.specialization_points_gained || 0) > 0
        || (ch.attribute_points_pending || 0) > 0) && (
        <div className="flex flex-wrap items-center gap-2 mb-1.5 text-[10px] text-gray-400">
          {(ch.attribute_points_gained || 0) > 0 && (
            <span>
              属性点 +{ch.attribute_points_gained}
              {ch.attribute_points_pending
                ? `（待分配 ${ch.attribute_points_pending}）`
                : "（已自动分配到最低属性）"}
            </span>
          )}
          {(ch.specialization_points_gained || 0) > 0 && (
            <span>
              专精点 +{ch.specialization_points_gained}（共 {ch.specialization_points_after}）
            </span>
          )}
        </div>
      )}

      <XpBar xp={ch.xp_after} needed={ch.xp_needed} level={ch.level_after} />

      {ch.capped && (
        <div className="text-[10px] text-gray-500 mt-1.5">⛔ {ch.cap_reason}</div>
      )}
    </div>
  );
}

export default function CombatSettlement({
  settlement,
  busy = false,
  error = null,
  pickedCardId = null,
  onCardPick,
  onConfirm,
  onRetry,
  isTest = false,
}: Props) {
  const rewards = settlement.rewards;
  const cards = rewards?.cards || [];

  return (
    <div className="combat-overlay-enter absolute inset-0 flex items-center justify-center bg-black/75 z-40 p-4">
      <div className="bg-surface-card border border-combat-border rounded-2xl p-6 w-full max-w-2xl max-h-[88vh] overflow-y-auto shadow-2xl">
        {/* 标题 */}
        <div className="text-center mb-4">
          <div className="text-2xl font-black font-display tracking-widest text-combat-gold">
            战斗结算
          </div>
          <div className="text-xs text-gray-500 font-display mt-1">
            {settlement.encounter_name || settlement.encounter_id} · 共 {settlement.rounds} 回合
            {settlement.victory ? " · 胜利" : settlement.winner === "escaped" ? " · 撤退" : " · 失利"}
          </div>
        </div>

        {/* 经验公式说明 */}
        {rewards?.xp_formula && (
          <div className="text-[10px] text-gray-600 font-mono text-center mb-3">
            {rewards.xp_formula}
          </div>
        )}

        {/* 无奖励提示 */}
        {!settlement.has_reward && settlement.empty_message && (
          <div className="text-center text-sm text-gray-400 font-display py-6 mb-3 rounded-lg bg-gray-800/40 border border-combat-border/60">
            {settlement.empty_message}
          </div>
        )}

        {/* 角色结算 */}
        {settlement.characters.length > 0 && (
          <div className="mb-4">
            <div className="text-[10px] text-gray-500 font-display tracking-wider mb-2">
              参战角色（{settlement.characters.length}）
            </div>
            <div className="space-y-2">
              {settlement.characters.map((ch) => (
                <CharacterRow key={ch.name} ch={ch} />
              ))}
            </div>
          </div>
        )}

        {/* 其他奖励 */}
        <div className="mb-4">
          <div className="text-[10px] text-gray-500 font-display tracking-wider mb-2">奖励</div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs px-2 py-1 rounded bg-amber-950/40 text-amber-300 border border-amber-900/50 font-mono">
              经验 {rewards?.xp_total ?? 0}
            </span>
            {(rewards?.items || []).map((it) => (
              <span
                key={it.name}
                className="text-xs px-2 py-1 rounded bg-cyan-950/40 text-cyan-200 border border-cyan-900/50 font-mono"
              >
                {it.name} ×{it.count}
              </span>
            ))}
            {(rewards?.items || []).length === 0 && (
              <span className="text-xs text-gray-600 font-display">无掉落物品</span>
            )}
          </div>
          {(rewards?.unwired || []).length > 0 && (
            <div className="text-[10px] text-gray-600 mt-2">
              遭遇声明了尚未接入结算的奖励字段：{rewards.unwired.join("、")}
            </div>
          )}
        </div>

        {/* 战后选卡 */}
        {cards.length > 0 && (
          <div className="mb-4">
            <div className="text-[10px] text-gray-500 font-display tracking-wider mb-2">
              选择一张卡加入卡组（下场战斗可用）
            </div>
            <div className="flex gap-2">
              {cards.map((c) => (
                <button
                  key={c.card_id}
                  className={"flex-1 text-left px-3 py-2 rounded-lg border transition-all " + (
                    pickedCardId === c.card_id
                      ? "border-cyan-400 bg-cyan-900/40 text-cyan-100"
                      : pickedCardId
                      ? "border-gray-700 bg-gray-900/40 text-gray-500 opacity-60"
                      : "border-gray-700 bg-gray-900/60 hover:bg-gray-800 text-gray-200"
                  )}
                  onClick={() => onCardPick?.(c.card_id)}
                  disabled={!!pickedCardId}
                >
                  <div className="text-xs font-bold">{c.name}</div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{c.description}</div>
                  <div className="text-[9px] text-gray-600 mt-1">费用 {c.cost} · {c.class_required}</div>
                </button>
              ))}
            </div>
            {pickedCardId && (
              <div className="text-emerald-300 text-xs mt-2">✅ 已加入卡组（下场战斗可用）</div>
            )}
          </div>
        )}

        {/* 写回失败提示 */}
        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg bg-red-950/50 border border-red-900/60 text-red-300 text-xs">
            {error}
          </div>
        )}

        {/* 操作 */}
        <div className="flex justify-center gap-3">
          {error && onRetry && (
            <button
              className="px-6 py-2.5 bg-red-900/60 hover:bg-red-800/60 text-red-200 rounded-lg transition-all border border-red-800/60 font-display tracking-wider"
              onClick={onRetry}
              disabled={busy}
            >
              重试结算
            </button>
          )}
          <button
            className="px-8 py-2.5 bg-cyan-900/70 hover:bg-cyan-800/70 text-cyan-200 rounded-lg transition-all border border-cyan-800/50 font-display tracking-wider disabled:opacity-50"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "结算中…" : isTest ? "结束测试" : "确认结算"}
          </button>
        </div>
      </div>
    </div>
  );
}
