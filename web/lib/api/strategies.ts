import type { RotationStrategy } from "@/lib/api/types";

export interface StrategyOption {
  value: RotationStrategy;
  label: string;
  description: string;
}

export const ROTATION_STRATEGIES: readonly StrategyOption[] = [
  { value: "round_robin", label: "By list", description: "Next proxy in list order on every connection, skipping failed ones." },
  { value: "random", label: "Random", description: "A random healthy proxy on every connection." },
  { value: "lowest_latency", label: "Fastest", description: "The lowest-latency healthy proxy, falling back down the list if it fails." },
  { value: "weighted_health", label: "Best quality", description: "Random, but weighted towards proxies with higher health scores." },
  { value: "sticky", label: "No rotation", description: "Stay on one proxy until it fails, then move to the next and stay there." },
];

export const STRATEGY_VALUES = ROTATION_STRATEGIES.map((option) => option.value) as [RotationStrategy, ...RotationStrategy[]];

export function strategyLabel(value: RotationStrategy): string {
  return ROTATION_STRATEGIES.find((option) => option.value === value)?.label ?? value;
}
