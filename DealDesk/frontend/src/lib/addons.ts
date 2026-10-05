/** The free extras the agent can recognise. Same list as the backend (negotiation/addons.py). The values are only suggestions in US dollars. */
export interface AddonInfo {
  key: string;
  label: string;
  suggestedUsd: number;
}

export const ADDONS: AddonInfo[] = [
  { key: "charger", label: "Charger", suggestedUsd: 20 },
  { key: "handsfree", label: "Hands-free or earphones", suggestedUsd: 15 },
  { key: "case", label: "Case or cover", suggestedUsd: 10 },
  { key: "screen_protector", label: "Screen protector", suggestedUsd: 8 },
  { key: "delivery", label: "Free delivery", suggestedUsd: 15 },
  { key: "warranty", label: "Extended warranty", suggestedUsd: 30 },
  { key: "bag", label: "Bag or sleeve", suggestedUsd: 20 },
  { key: "mouse", label: "Mouse", suggestedUsd: 10 },
];
