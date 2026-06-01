import { describe, expect, it } from "vitest";

import { NEWS_CONTEXT_SCHEMA, NEWS_CONTEXT_TASK, buildContextPrompt } from "./aiFill";
import { basicInfoFromDict } from "./schema";

describe("news_video aiFill", () => {
  it("schema constrains all 15 fields as required strings", () => {
    expect(NEWS_CONTEXT_SCHEMA.type).toBe("object");
    expect(NEWS_CONTEXT_SCHEMA.required).toHaveLength(15);
    expect(NEWS_CONTEXT_SCHEMA.additionalProperties).toBe(false);
    expect(NEWS_CONTEXT_SCHEMA.properties.host).toEqual({ type: "string" });
    for (const f of NEWS_CONTEXT_SCHEMA.required) {
      expect(NEWS_CONTEXT_SCHEMA.properties[f]).toEqual({ type: "string" });
    }
    expect(NEWS_CONTEXT_TASK).toBe("news.realtime");
  });

  it("fills platform metadata + basic_info into the prompt", () => {
    const basic = basicInfoFromDict({ host: "Vance", episode_topic: "Budget" });
    const prompt = buildContextPrompt(basic, {
      webpage_url: "https://x.test/v",
      uploader: "Gov Channel",
      description: "A press briefing",
      tags: ["politics", "budget"],
    });
    expect(prompt).toContain("https://x.test/v");
    expect(prompt).toContain("上传者: Gov Channel");
    expect(prompt).toContain("标签: politics, budget");
    expect(prompt).toContain('"host": "Vance"'); // basic_info embedded as JSON
    expect(prompt).toContain("15 字段全 string");
  });

  it("renders empty platform fields as em-dash and falls back across url keys", () => {
    const prompt = buildContextPrompt(basicInfoFromDict({}), { original_url: "https://fallback" });
    expect(prompt).toContain("https://fallback"); // original_url used when webpage_url absent
    expect(prompt).toContain("上传者: —");
    expect(prompt).toContain("描述: —");
    expect(prompt).toContain("标签: —");
  });

  it("caps tags at 20", () => {
    const tags = Array.from({ length: 30 }, (_, i) => `t${i}`);
    const prompt = buildContextPrompt(basicInfoFromDict({}), { tags });
    expect(prompt).toContain("t19");
    expect(prompt).not.toContain("t20");
  });
});
