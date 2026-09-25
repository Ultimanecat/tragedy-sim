import { describe, expect, it } from "vitest";
import { AI_CHOICES, availableAiChoices, scenarioOptionLabel } from "./lobbyChoices";

describe("lobby choices", () => {
  it("documents every AI strategy with a unique label and explanation", () => {
    expect(AI_CHOICES).toHaveLength(16);
    expect(new Set(AI_CHOICES.map(choice => choice.id)).size).toBe(AI_CHOICES.length);
    expect(AI_CHOICES.every(choice => choice.label && choice.description)).toBe(true);
    expect(AI_CHOICES.find(choice => choice.id === "risk_aware_protagonist")?.description).toContain("并非最强");
  });

  it("filters strategies by role, module, and team size", () => {
    const soloFs = availableAiChoices("a", "FS", 1).map(choice => choice.id);
    const trioFs = availableAiChoices("a", "FS", 3).map(choice => choice.id);
    const soloMc = availableAiChoices("a", "MC", 1).map(choice => choice.id);
    const mastermindBtx = availableAiChoices("m", "BTX", 1).map(choice => choice.id);
    const mastermindFs = availableAiChoices("m", "FS", 1).map(choice => choice.id);
    expect(soloFs).toContain("particle_ensemble_protagonist");
    expect(soloFs).toContain("oracle_cards_protagonist");
    expect(trioFs).not.toContain("particle_ensemble_protagonist");
    expect(soloMc).not.toContain("oracle_cards_protagonist");
    expect(soloMc).not.toContain("ismcts_protagonist");
    expect(mastermindBtx).toContain("belief_joint_mastermind");
    expect(mastermindFs).not.toContain("belief_joint_mastermind");
    expect(mastermindFs).not.toContain("defensive_protagonist");
  });

  it("shows the ruleset in each scenario option", () => {
    expect(scenarioOptionLabel({
      id: "example", title: "示例", module: "BTX", days: 4,
      loops: 3, loop_options: [3, 4], source: "library",
    })).toContain("[BTX] 示例 · 4 天/3–4 轮");
  });
});
