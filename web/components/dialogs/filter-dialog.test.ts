import { describe, expect, it } from "vitest";
import { buildFilterRules, filterFormSchema } from "@/components/dialogs/filter-dialog";

describe("filter editor", () => {
  it("normalizes countries and builds the versioned AST", async () => {
    const values = await filterFormSchema.parseAsync({ name: "Google UK", countries: "gb, de", minimumScore: "85", maximumLatency: "500", targetId: "f8dfcfdd-9927-4ebc-b3ef-aee58de3fe9b", targetAvailability: "available", catalogSelection: "combined" });
    const ast = buildFilterRules(values);
    expect(ast.version).toBe(1);
    expect(ast.root.op).toBe("all");
    expect(ast.root.rules).toContainEqual({ op: "predicate", field: "country", operator: "in", value: ["GB", "DE"] });
    expect(ast.root.rules).toContainEqual({ op: "predicate", field: "target_availability", operator: "eq", value: "available", target_id: "f8dfcfdd-9927-4ebc-b3ef-aee58de3fe9b" });
  });

  it("rejects malformed country codes", () => {
    expect(() => filterFormSchema.parse({ name: "Bad", countries: "United Kingdom", minimumScore: 70, maximumLatency: "", targetId: "none", targetAvailability: "available", catalogSelection: "private" })).toThrow();
  });
});
