import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  bChangeText,
  bDurationText,
  bVisualState,
} from "../app/lib/industry-b-health.mjs";

test("core identity and B risk are independent visual dimensions", () => {
  assert.deepEqual(
    bVisualState({ pool_rank: 1 }),
    {
      label: "B稳定",
      tone: "stable",
      status: "stable",
      core: true,
      coreLabel: "核心 Top1",
    },
  );
  assert.equal(
    bVisualState({ pool_rank: 2, smooth5_weak: true }).tone,
    "warning",
  );
  assert.equal(
    bVisualState({
      pool_rank: 1,
      smooth3_weak: true,
      formal_cooling: true,
    }).tone,
    "danger",
  );
});

test("duration copy describes a state, never a raw consecutive decline", () => {
  assert.equal(
    bDurationText({ weak_duration: 4 }),
    "B走弱状态已持续4个交易日",
  );
  assert.equal(bDurationText({ weak_duration: 0 }), "");
  assert.equal(bChangeText(1.26), "+1.3只");
  assert.equal(bChangeText(-0.04), "0只");
});

test("generated B health interface keeps the frozen Top100 and rank rules", async () => {
  const payload = JSON.parse(
    await readFile(
      new URL("../public/industry-b-health.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(payload.version, "industry-b-health/1");
  assert.equal(payload.snapshots.length, 52);
  assert.match(payload.definition.b_pool, /不是三个模板各自 Top100 的并集/);

  for (const snapshot of payload.snapshots) {
    assert.equal(snapshot.pool_total, 100);
    assert.equal(snapshot.industries.length, 31);
    assert.deepEqual(
      snapshot.industries.slice(0, 2).map(row => row.pool_rank),
      [1, 2],
    );
  }

  const latest = payload.snapshots.at(-1);
  const buildingMaterials = latest.industries.find(
    row => row.industry_code === "801710.SI",
  );
  assert.equal(buildingMaterials.status, "cooling");
  assert.equal(buildingMaterials.formal_cooling, true);
  assert.ok(buildingMaterials.weak_duration >= 1);
});
