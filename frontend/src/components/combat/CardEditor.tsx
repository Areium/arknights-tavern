import { useState, useEffect, useCallback } from "react";
import { useApi } from "../../hooks/useApi";
import type { CombatCardsDTO, CombatCardDTO, ClassCardsDTO, ClassCardDTO } from "../../types";

type CardData = CombatCardDTO | ClassCardDTO;

const RARITY_LABELS = ["", "★", "★★", "★★★", "★★★★", "★★★★★", "★★★★★★"];

const DAMAGE_TYPES = ["physical", "arts", "healing", "mixed"] as const;
const TARGET_PATTERNS = [
  "SINGLE", "ADJACENT", "CROSS", "LINE_3", "AREA_2X2", "GLOBAL",
  "ALL_ALLIES", "SELF",
] as const;
const TIERS = ["basic", "elite"] as const;
const COST_TYPES = ["sp", "passive"] as const;

interface Props {
  onClose?: () => void;
  /** 内嵌模式：不渲染模态框外壳 */
  embedded?: boolean;
  /** 内嵌模式下的实体名（角色或职业名） */
  entityName?: string;
  /** 内嵌模式下的实体类型 */
  entityType?: "character" | "class";
  /** 内嵌模式下的额外 className */
  className?: string;
}

export default function CardEditor({ onClose, embedded, entityName, entityType, className }: Props) {
  const api = useApi();

  const [characters, setCharacters] = useState<string[]>([]);
  const [selectedChar, setSelectedChar] = useState<string | null>(entityName && entityType === "character" ? entityName : null);
  const [selectedClass, setSelectedClass] = useState<string | null>(entityName && entityType === "class" ? entityName : null);
  const [cardsData, setCardsData] = useState<CombatCardsDTO | null>(null);
  const [classCardsData, setClassCardsData] = useState<ClassCardsDTO | null>(null);
  const [selectedCardIdx, setSelectedCardIdx] = useState<number | null>(null);
  const [editingCard, setEditingCard] = useState<CardData | null>(null);
  const [tab, setTab] = useState<"exclusive" | "class">("exclusive");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [cardTypeInput, setCardTypeInput] = useState("");
  const [tagInput, setTagInput] = useState("");

  const isClassMode = entityType === "class" || (!entityType && selectedClass);

  // ── Load character list / auto-load embedded entity ──
  useEffect(() => {
    if (embedded && entityName) {
      if (entityType === "character") {
        loadCharacter(entityName);
      } else if (entityType === "class") {
        loadClass(entityName);
      }
      return;
    }
    if (!embedded) {
      api.listCharactersWithCards().then(
        (res) => setCharacters(res.characters || []),
        () => setError("Failed to load character list")
      );
    }
  }, [embedded, entityName, entityType]);

  // ── Load character cards ──
  const loadCharacter = useCallback(async (name: string) => {
    setLoading(true);
    setError(null);
    setSelectedCardIdx(null);
    setEditingCard(null);
    setClassCardsData(null);
    try {
      const data = await api.getCharacterCards(name);
      setCardsData(data);
      setSelectedChar(name);
      setSelectedClass(null);
    } catch {
      setError("Failed to load cards");
      setCardsData(null);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // ── Load class cards ──
  const loadClass = useCallback(async (name: string) => {
    setLoading(true);
    setError(null);
    setSelectedCardIdx(null);
    setEditingCard(null);
    setCardsData(null);
    try {
      const data = await api.getClassCards(name);
      setClassCardsData(data);
      setSelectedClass(name);
      setSelectedChar(null);
    } catch {
      setError("Failed to load class cards");
      setClassCardsData(null);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // ── Select card for editing ──
  const selectCard = (idx: number) => {
    setSelectedCardIdx(idx);
    if (isClassMode) {
      const cards = classCardsData?.cards || [];
      if (idx >= 0 && idx < cards.length) {
        setEditingCard({ ...cards[idx] });
      }
    } else {
      const cards = tab === "exclusive"
        ? cardsData?.exclusive_cards
        : cardsData?.class_cards;
      if (cards && idx >= 0 && idx < cards.length) {
        setEditingCard({ ...cards[idx] });
      }
    }
  };

  // ── New card ──
  const newCard = () => {
    if (isClassMode) {
      const card: ClassCardDTO = {
        card_id: "",
        name: "",
        description: "",
        damage_type: "physical",
        min_damage: 0, max_damage: 0, atk_scale: 0,
        target: "SINGLE", range: 1, cost: 1,
        tier: "basic",
        class_required: selectedClass || "",
        owner: null,
      };
      setEditingCard(card);
    } else {
      const card: CombatCardDTO = {
        card_id: "",
        name: "",
        rarity: 1,
        category: tab,
        card_type: [],
        cost_type: "sp",
        cost: 1,
        damage_type: "physical",
        target: "SINGLE",
        range: 1,
        min_damage: 0,
        max_damage: 0,
        atk_scale: 0,
        tier: "basic",
        class_required: cardsData?.class_name || "any",
        description: "",
        effect: "",
        base_value: null,
        base_value_formula: null,
        check: null,
        plot_impact: null,
        usage_limit: null,
        condition: null,
        tags: [],
        owner: null,
      };
      setEditingCard(card);
    }
    setSelectedCardIdx(-1);
  };

  // ── Delete card ──
  const deleteCard = async () => {
    if (selectedCardIdx == null || selectedCardIdx < 0) return;
    const cardId = getCardList()[selectedCardIdx]?.card_id;
    if (!cardId) return;

    if (isClassMode && selectedClass) {
      try {
        const result = await api.deleteClassCard(selectedClass, cardId);
        setClassCardsData((prev) => prev ? {
          ...prev,
          cards: prev.cards.filter((c) => c.card_id !== cardId),
          _hash: result._hash,
        } : null);
      } catch (e: any) { setError(e?.message || "Delete failed"); return; }
    } else if (selectedChar) {
      try {
        const result = await api.deleteCharacterCard(selectedChar, cardId);
        setCardsData((prev) => {
          if (!prev) return null;
          return {
            ...prev,
            exclusive_cards: prev.exclusive_cards.filter((c) => c.card_id !== cardId),
            class_cards: prev.class_cards.filter((c) => c.card_id !== cardId),
            _hash: result._hash,
          };
        });
      } catch (e: any) { setError(e?.message || "Delete failed"); return; }
    }
    setEditingCard(null);
    setSelectedCardIdx(null);
  };

  // ── Save all cards ──
  const saveCards = async () => {
    if (isClassMode && classCardsData && selectedClass) {
      setSaving(true); setError(null); setSuccess(null);
      try {
        const result = await api.saveClassCards(selectedClass, classCardsData);
        setClassCardsData({ ...classCardsData, _hash: result._hash });
        setSuccess("Saved");
        setTimeout(() => setSuccess(null), 2000);
      } catch (e: any) { setError(e?.message || "Save failed"); }
      finally { setSaving(false); }
    } else if (cardsData && selectedChar) {
      setSaving(true); setError(null); setSuccess(null);
      try {
        const result = await api.saveCharacterCards(selectedChar, cardsData);
        setCardsData({ ...cardsData, _hash: result._hash });
        setSuccess("Saved");
        setTimeout(() => setSuccess(null), 2000);
      } catch (e: any) { setError(e?.message || "Save failed"); }
      finally { setSaving(false); }
    }
  };

  // ── Apply editing card back ──
  const applyEdit = () => {
    if (!editingCard) return;

    if (isClassMode && classCardsData) {
      const cards = [...classCardsData.cards];
      if (selectedCardIdx != null && selectedCardIdx >= 0 && selectedCardIdx < cards.length) {
        cards[selectedCardIdx] = editingCard as ClassCardDTO;
      } else if (selectedCardIdx === -1) {
        const newCard = { ...editingCard, card_id: `${selectedClass}_${cards.length.toString().padStart(2, "0")}` } as ClassCardDTO;
        cards.push(newCard);
      }
      setClassCardsData({ ...classCardsData, cards });
    } else if (cardsData) {
      const key = tab === "exclusive" ? "exclusive_cards" : "class_cards";
      const cards = [...(cardsData[key] || [])];
      if (selectedCardIdx != null && selectedCardIdx >= 0 && selectedCardIdx < cards.length) {
        cards[selectedCardIdx] = editingCard as CombatCardDTO;
      } else if (selectedCardIdx === -1) {
        const newCard = { ...editingCard, card_id: `${selectedChar}_${cards.length.toString().padStart(2, "0")}` } as CombatCardDTO;
        cards.push(newCard);
      }
      setCardsData({ ...cardsData, [key]: cards });
    }
    setEditingCard(null);
    setSelectedCardIdx(null);
  };

  // ── Helpers ──

  const getCardList = (): CardData[] => {
    if (isClassMode) return classCardsData?.cards || [];
    if (tab === "exclusive") return cardsData?.exclusive_cards || [];
    return cardsData?.class_cards || [];
  };

  const isCombatCard = (_card: CardData): _card is CombatCardDTO => {
    return !isClassMode;
  };

  const isActive = embedded || !!selectedChar || !!selectedClass;
  const activeName = selectedChar || selectedClass || "";

  // ── Render ──

  const header = (
    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
      <div className="flex items-center gap-3 text-sm">
        <span className="text-gray-400">{isClassMode ? "Class Cards" : "Card Editor"}</span>
        {!embedded && (
          <select
            className="input py-1 text-sm"
            value={isClassMode ? `class:${selectedClass || ""}` : selectedChar || ""}
            onChange={(e) => {
              const v = e.target.value;
              if (v.startsWith("class:")) {
                loadClass(v.slice(6));
              } else if (v) {
                loadCharacter(v);
              }
            }}
          >
            <option value="">Select...</option>
            <optgroup label="Characters">
              {characters.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </optgroup>
            <optgroup label="Classes">
              {(isClassMode && selectedClass ? [selectedClass] : []).map((c) => (
                <option key={`class:${c}`} value={`class:${c}`}>{c}</option>
              ))}
            </optgroup>
          </select>
        )}
        {embedded && activeName && (
          <span className="text-gray-500 text-xs">
            {isClassMode ? "class" : "character"}: {activeName}
            {isClassMode
              ? (classCardsData && ` — ${classCardsData.cards.length} cards`)
              : (cardsData && ` — ${cardsData.exclusive_cards.length} + ${cardsData.class_cards.length} cards`)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {success && <span className="text-green-400 text-xs">{success}</span>}
        {error && <span className="text-red-400 text-xs">{error}</span>}
        {!embedded && onClose && (
          <button className="btn btn-sm btn-ghost text-gray-400" onClick={onClose}>
            Close
          </button>
        )}
      </div>
    </div>
  );

  if (!isActive) {
    const inner = (
      <div className="flex items-center justify-center h-full text-gray-500">
        <div>
          {header}
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm">Select a character or class to edit cards</p>
          </div>
        </div>
      </div>
    );
    if (embedded) return inner;
    return (
      <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center">
        <div className="bg-gray-900 border border-gray-700 rounded-lg flex flex-col"
             style={{ width: "min(95vw, 1100px)", height: "min(90vh, 700px)" }}>
          {inner}
        </div>
      </div>
    );
  }

  if (loading) {
    return embedded
      ? <div className="flex items-center justify-center h-full text-gray-500">Loading...</div>
      : (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center">
          <div className="bg-gray-900 border border-gray-700 rounded-lg flex flex-col"
               style={{ width: "min(95vw, 1100px)", height: "min(90vh, 700px)" }}>
            {header}
            <div className="flex-1 flex items-center justify-center text-gray-500">Loading...</div>
          </div>
        </div>
      );
  }

  const cardList = getCardList();

  const body = (
    <>
      {!isClassMode && (
        <div className="flex border-b border-gray-700 px-4 shrink-0">
          <button
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === "exclusive"
                ? "border-amber-500 text-amber-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
            onClick={() => { setTab("exclusive"); setSelectedCardIdx(null); setEditingCard(null); }}
          >
            Exclusive ({cardsData?.exclusive_cards.length || 0})
          </button>
          <button
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === "class"
                ? "border-amber-500 text-amber-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
            onClick={() => { setTab("class"); setSelectedCardIdx(null); setEditingCard(null); }}
          >
            Class Cards ({cardsData?.class_cards.length || 0})
          </button>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        {/* Card list */}
        <div className="w-56 border-r border-gray-700 overflow-y-auto flex flex-col shrink-0">
          <div className="p-2">
            <button className="btn btn-sm btn-ghost text-xs w-full text-left text-gray-400 hover:text-white"
                    onClick={newCard}>
              + New Card
            </button>
          </div>
          {cardList.map((card, idx) => (
            <button
              key={card.card_id || idx}
              className={`px-3 py-2 text-left text-sm border-b border-gray-800 transition-colors ${
                selectedCardIdx === idx
                  ? "bg-amber-500/10 text-amber-300 border-l-2 border-l-amber-500"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              }`}
              onClick={() => selectCard(idx)}
            >
              <div className="truncate text-xs font-medium">
                {isCombatCard(card) ? `${RARITY_LABELS[(card as CombatCardDTO).rarity] || ""} ` : ""}{card.name || "(unnamed)"}
              </div>
              <div className="text-xs text-gray-600 mt-0.5">
                {isCombatCard(card)
                  ? ((card as CombatCardDTO).cost_type === "passive" ? "Passive" : `${(card as CombatCardDTO).cost} SP`)
                  : `${card.cost} SP`}
                {isCombatCard(card) && (card as CombatCardDTO)._needs_review && " ⚠"}
              </div>
            </button>
          ))}
        </div>

        {/* Editor form */}
        <div className="flex-1 overflow-y-auto p-4">
          {editingCard ? (
            <div className="space-y-3 max-w-lg">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-300">
                  {selectedCardIdx === -1 ? "New Card" : "Edit Card"}
                </h3>
                <div className="flex gap-2">
                  <button className="btn btn-sm btn-primary text-xs" onClick={applyEdit}>
                    Apply
                  </button>
                  {selectedCardIdx !== -1 && (
                    <button className="btn btn-sm btn-ghost text-xs text-red-400" onClick={deleteCard}>
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {/* Name */}
              <FormField label="Name">
                <input className="input text-sm w-full" value={editingCard.name}
                       onChange={(e) => setEditingCard({ ...editingCard, name: e.target.value })} />
              </FormField>

              {isCombatCard(editingCard) && (
                <>
                  {/* Rarity */}
                  <FormField label="Rarity">
                    <select className="input text-sm w-full" value={(editingCard as CombatCardDTO).rarity}
                            onChange={(e) => setEditingCard({ ...editingCard, rarity: Number(e.target.value) })}>
                      {[1,2,3,4,5,6].map((r) => (
                        <option key={r} value={r}>{RARITY_LABELS[r]} ({r})</option>
                      ))}
                    </select>
                  </FormField>

                  {/* Card type tags */}
                  <FormField label="Card Types">
                    <div className="flex flex-wrap gap-1 mb-1">
                      {(editingCard as CombatCardDTO).card_type.map((t, i) => (
                        <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">
                          {t}
                          <button className="text-gray-500 hover:text-red-400"
                                  onClick={() => {
                                    const types = [...(editingCard as CombatCardDTO).card_type];
                                    types.splice(i, 1);
                                    setEditingCard({ ...editingCard, card_type: types });
                                  }}>×</button>
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-1">
                      <input className="input text-xs flex-1" placeholder="Add type..."
                             value={cardTypeInput}
                             onChange={(e) => setCardTypeInput(e.target.value)}
                             onKeyDown={(e) => {
                               if (e.key === "Enter" && cardTypeInput.trim()) {
                                 setEditingCard({
                                   ...editingCard,
                                   card_type: [...(editingCard as CombatCardDTO).card_type, cardTypeInput.trim()],
                                 });
                                 setCardTypeInput("");
                                 e.preventDefault();
                               }
                             }} />
                    </div>
                  </FormField>

                  {/* Cost type */}
                  <FormField label="Cost Type">
                    <select className="input text-sm w-full" value={(editingCard as CombatCardDTO).cost_type}
                            onChange={(e) => setEditingCard({
                              ...editingCard,
                              cost_type: e.target.value as "sp" | "passive",
                              cost: e.target.value === "passive" ? 0 : (editingCard as CombatCardDTO).cost,
                            })}>
                      {COST_TYPES.map((ct) => (
                        <option key={ct} value={ct}>{ct}</option>
                      ))}
                    </select>
                  </FormField>
                </>
              )}

              {/* Cost */}
              {(isCombatCard(editingCard) ? (editingCard as CombatCardDTO).cost_type !== "passive" : true) && (
                <FormField label="Cost (SP)">
                  <input className="input text-sm w-full" type="number" min={0} max={20}
                         value={(editingCard as any).cost ?? 0}
                         onChange={(e) => setEditingCard({ ...editingCard, cost: Number(e.target.value) } as any)} />
                </FormField>
              )}

              {/* Damage type & Target */}
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Damage Type">
                  <select className="input text-sm w-full" value={editingCard.damage_type}
                          onChange={(e) => setEditingCard({ ...editingCard, damage_type: e.target.value as any })}>
                    {DAMAGE_TYPES.map((dt) => (
                      <option key={dt} value={dt}>{dt}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="Target Pattern">
                  <select className="input text-sm w-full" value={editingCard.target}
                          onChange={(e) => setEditingCard({ ...editingCard, target: e.target.value })}>
                    {TARGET_PATTERNS.map((tp) => (
                      <option key={tp} value={tp}>{tp}</option>
                    ))}
                  </select>
                </FormField>
              </div>

              {/* Range & Tier */}
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Range">
                  <input className="input text-sm w-full" type="number" min={-1} max={10}
                         value={editingCard.range}
                         onChange={(e) => setEditingCard({ ...editingCard, range: Number(e.target.value) })} />
                </FormField>
                <FormField label="Tier">
                  <select className="input text-sm w-full" value={editingCard.tier}
                          onChange={(e) => setEditingCard({ ...editingCard, tier: e.target.value as any })}>
                    {TIERS.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </FormField>
              </div>

              {/* Damage values */}
              <div className="grid grid-cols-3 gap-3">
                <FormField label="Min Damage">
                  <input className="input text-sm w-full" type="number" min={0}
                         value={(editingCard as any).min_damage ?? 0}
                         onChange={(e) => setEditingCard({ ...editingCard, min_damage: Number(e.target.value) } as any)} />
                </FormField>
                <FormField label="Max Damage">
                  <input className="input text-sm w-full" type="number" min={0}
                         value={(editingCard as any).max_damage ?? 0}
                         onChange={(e) => setEditingCard({ ...editingCard, max_damage: Number(e.target.value) } as any)} />
                </FormField>
                <FormField label="ATK Scale">
                  <input className="input text-sm w-full" type="number" min={0} max={5} step={0.1}
                         value={(editingCard as any).atk_scale ?? 0}
                         onChange={(e) => setEditingCard({ ...editingCard, atk_scale: Number(e.target.value) } as any)} />
                </FormField>
              </div>

              {/* Description */}
              <FormField label="Description">
                <textarea className="input text-sm w-full resize-y" rows={3}
                          value={editingCard.description}
                          onChange={(e) => setEditingCard({ ...editingCard, description: e.target.value })} />
              </FormField>

              {/* Character-only fields */}
              {isCombatCard(editingCard) && (
                <>
                  <FormField label="Class Required">
                    <input className="input text-sm w-full"
                           value={(editingCard as CombatCardDTO).class_required || ""}
                           onChange={(e) => setEditingCard({ ...editingCard, class_required: e.target.value })} />
                  </FormField>

                  <div className="grid grid-cols-2 gap-3">
                    <FormField label="Base Value">
                      <input className="input text-sm w-full" type="number"
                             value={(editingCard as CombatCardDTO).base_value ?? ""}
                             onChange={(e) => setEditingCard({
                               ...editingCard,
                               base_value: e.target.value ? Number(e.target.value) : null,
                             })} />
                    </FormField>
                    <FormField label="Formula">
                      <input className="input text-sm w-full" placeholder="e.g. 源石技艺适应性"
                             value={(editingCard as CombatCardDTO).base_value_formula || ""}
                             onChange={(e) => setEditingCard({
                               ...editingCard,
                               base_value_formula: e.target.value || null,
                             })} />
                    </FormField>
                  </div>

                  <FormField label="Effect">
                    <textarea className="input text-sm w-full resize-y" rows={4}
                              value={(editingCard as CombatCardDTO).effect}
                              onChange={(e) => setEditingCard({
                                ...editingCard,
                                effect: e.target.value,
                                description: e.target.value,
                              })} />
                  </FormField>

                  <FormField label="Check (Judgment)">
                    <div className="grid grid-cols-2 gap-2">
                      <input className="input text-sm" placeholder="Roll (e.g. d20 + base_value)"
                             value={(editingCard as CombatCardDTO).check?.roll || ""}
                             onChange={(e) => setEditingCard({
                               ...editingCard,
                               check: { ...(editingCard as CombatCardDTO).check, roll: e.target.value, description: (editingCard as CombatCardDTO).check?.description || "", vs: (editingCard as CombatCardDTO).check?.vs || "" },
                             })} />
                      <input className="input text-sm" placeholder="VS (e.g. target_magic_defense_dc)"
                             value={(editingCard as CombatCardDTO).check?.vs || ""}
                             onChange={(e) => setEditingCard({
                               ...editingCard,
                               check: { ...(editingCard as CombatCardDTO).check, vs: e.target.value, description: (editingCard as CombatCardDTO).check?.description || "", roll: (editingCard as CombatCardDTO).check?.roll || "" },
                             })} />
                    </div>
                  </FormField>

                  <FormField label="Plot Impact">
                    <textarea className="input text-sm w-full resize-y" rows={2}
                              value={(editingCard as CombatCardDTO).plot_impact || ""}
                              onChange={(e) => setEditingCard({
                                ...editingCard,
                                plot_impact: e.target.value || null,
                              })} />
                  </FormField>

                  <FormField label="Tags">
                    <div className="flex flex-wrap gap-1 mb-1">
                      {(editingCard as CombatCardDTO).tags.map((t, i) => (
                        <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300">
                          {t}
                          <button className="text-gray-500 hover:text-red-400"
                                  onClick={() => {
                                    const tags = [...(editingCard as CombatCardDTO).tags];
                                    tags.splice(i, 1);
                                    setEditingCard({ ...editingCard, tags });
                                  }}>×</button>
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-1">
                      <input className="input text-xs flex-1" placeholder="Add tag..."
                             value={tagInput}
                             onChange={(e) => setTagInput(e.target.value)}
                             onKeyDown={(e) => {
                               if (e.key === "Enter" && tagInput.trim()) {
                                 setEditingCard({
                                   ...editingCard,
                                   tags: [...(editingCard as CombatCardDTO).tags, tagInput.trim()],
                                 });
                                 setTagInput("");
                                 e.preventDefault();
                               }
                             }} />
                    </div>
                  </FormField>

                  <FormField label="Condition (trigger)">
                    <input className="input text-sm w-full"
                           value={(editingCard as CombatCardDTO).condition || ""}
                           onChange={(e) => setEditingCard({
                             ...editingCard,
                             condition: e.target.value || null,
                           })} />
                  </FormField>

                  <FormField label="Usage Limit">
                    <div className="grid grid-cols-2 gap-2">
                      <input className="input text-sm" placeholder="Scope"
                             value={(editingCard as CombatCardDTO).usage_limit?.scope || ""}
                             onChange={(e) => setEditingCard({
                               ...editingCard,
                               usage_limit: { scope: e.target.value, count: (editingCard as CombatCardDTO).usage_limit?.count || 1 },
                             })} />
                      <input className="input text-sm" type="number" min={1} placeholder="Count"
                             value={(editingCard as CombatCardDTO).usage_limit?.count || ""}
                             onChange={(e) => setEditingCard({
                               ...editingCard,
                               usage_limit: { scope: (editingCard as CombatCardDTO).usage_limit?.scope || "encounter", count: Number(e.target.value) },
                             })} />
                    </div>
                  </FormField>
                </>
              )}

              {!isCombatCard(editingCard) && (
                <FormField label="Class Required">
                  <input className="input text-sm w-full"
                         value={(editingCard as ClassCardDTO).class_required || ""}
                         onChange={(e) => setEditingCard({ ...editingCard, class_required: e.target.value })} />
                </FormField>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-600 text-sm">
              Select a card from the list, or click '+ New Card'
            </div>
          )}
        </div>
      </div>
    </>
  );

  // Footer
  const footer = (
    <div className="flex items-center justify-between px-4 py-2 border-t border-gray-700 shrink-0">
      <span className="text-xs text-gray-600">
        Hash: {(cardsData?._hash || classCardsData?._hash)?.slice(0, 8)}...
      </span>
      <button
        className="btn btn-sm btn-primary"
        disabled={saving}
        onClick={saveCards}
      >
        {saving ? "Saving..." : "Save All Changes"}
      </button>
    </div>
  );

  if (embedded) {
    return (
      <div className={`flex flex-col h-full ${className || ""}`}>
        {header}
        {body}
        {footer}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center">
      <div className="bg-gray-900 border border-gray-700 rounded-lg flex flex-col"
           style={{ width: "min(95vw, 1100px)", height: "min(90vh, 700px)" }}>
        {header}
        {body}
        {footer}
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-500 mb-1 block">{label}</span>
      {children}
    </label>
  );
}
