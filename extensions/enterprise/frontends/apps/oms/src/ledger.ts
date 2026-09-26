export type Grant = { id: string; method: "gift" | "recharge"; remaining: number };

export function consumeGiftFirst(grants: Grant[], amount: number): {
  status: "consumed" | "insufficient";
  allocations: { id: string; amount: number }[];
  remaining: Grant[];
} {
  if (!Number.isFinite(amount) || amount <= 0 || grants.some((grant) => !Number.isFinite(grant.remaining) || grant.remaining < 0)) {
    throw new Error("消耗量和余额必须为正的可核对数值");
  }
  if (grants.reduce((sum, grant) => sum + grant.remaining, 0) < amount) {
    return { status: "insufficient", allocations: [], remaining: grants.map((grant) => ({ ...grant })) };
  }
  let needed = amount;
  const allocations: { id: string; amount: number }[] = [];
  const remaining = grants.map((grant) => ({ ...grant }));
  const order = remaining.map((grant, index) => ({ grant, index }))
    .sort((a, b) => Number(a.grant.method === "recharge") - Number(b.grant.method === "recharge") || a.index - b.index);
  for (const item of order) {
    if (needed === 0) break;
    const used = Math.min(item.grant.remaining, needed);
    if (used > 0) allocations.push({ id: item.grant.id, amount: used });
    item.grant.remaining -= used;
    needed -= used;
  }
  return { status: "consumed", allocations, remaining };
}
