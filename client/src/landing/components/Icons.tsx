// Inline SVG icons. Kept as small components so the landing page needs no icon
// library — consistent with the project's minimal dependency philosophy.

type IconProps = { className?: string };

const base = {
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const IconShield = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 3l7 3v5c0 4.4-3 8.2-7 9.5-4-1.3-7-5.1-7-9.5V6l7-3z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
);

export const IconBolt = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M13 2L4.5 13.5H11l-1 8.5L19.5 10.5H13l0-8.5z" />
  </svg>
);

export const IconCoins = (p: IconProps) => (
  <svg {...base} {...p}>
    <ellipse cx="8" cy="6" rx="6" ry="3" />
    <path d="M2 6v5c0 1.66 2.7 3 6 3s6-1.34 6-3V6" />
    <path d="M2 11v5c0 1.66 2.7 3 6 3 1 0 2-.13 2.8-.35" />
    <ellipse cx="16" cy="15" rx="6" ry="3" />
    <path d="M10 15v3c0 1.66 2.7 3 6 3s6-1.34 6-3v-3" />
  </svg>
);

export const IconChart = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 20V4" />
    <path d="M4 20h16" />
    <path d="M7 16l3.5-4 3 2.5L20 7" />
  </svg>
);

export const IconLock = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 018 0v3" />
    <circle cx="12" cy="15.5" r="1.2" />
  </svg>
);

export const IconGlobe = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18" />
    <path d="M12 3c2.5 2.5 3.8 5.7 3.8 9S14.5 18.5 12 21c-2.5-2.5-3.8-5.7-3.8-9S9.5 5.5 12 3z" />
  </svg>
);

export const IconArrow = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M5 12h14" />
    <path d="M13 6l6 6-6 6" />
  </svg>
);

export const IconCheck = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M5 12l5 5L20 7" />
  </svg>
);

const FEATURE_ICONS = {
  shield: IconShield,
  bolt: IconBolt,
  coins: IconCoins,
  chart: IconChart,
  lock: IconLock,
  globe: IconGlobe,
} as const;

export type FeatureIconName = keyof typeof FEATURE_ICONS;

export const FeatureIcon = ({ name, className }: { name: FeatureIconName; className?: string }) => {
  const Cmp = FEATURE_ICONS[name];
  return <Cmp className={className} />;
};
