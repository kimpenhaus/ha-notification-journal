interface CustomIcon {
  path: string;
  secondaryPath?: string;
  viewBox?: string;
}

interface CustomIconset {
  getIcon(name: string): Promise<CustomIcon | undefined>;
  getIconList(): Promise<{ name: string }[]>;
}

declare global {
  interface Window {
    customIcons?: Record<string, CustomIconset>;
  }
}

const ICONS: Record<string, CustomIcon> = {
  "bell-stack": {
    path: "M12 1.39c-2.73 0 -4.62 2.1 -4.62 4.83v2.73l-1.26 2.1c-0.21 0.42 0.1 0.84 0.53 0.84h10.71c0.42 0 0.73 -0.42 0.53 -0.84l-1.26 -2.1v-2.73c0 -2.73 -1.89 -4.83 -4.62 -4.83zM10.32 12.53a1.68 1.68 0 0 0 3.36 0zM4.12 20.3h15.75a1.16 1.16 0 0 1 0 2.31h-15.75a1.16 1.16 0 0 1 0 -2.31z",
    secondaryPath:
      "M5.81 13.99h12.39a1.16 1.16 0 0 1 0 2.31h-12.39a1.16 1.16 0 0 1 0 -2.31zM4.96 17.14h14.07a1.16 1.16 0 0 1 0 2.31h-14.07a1.16 1.16 0 0 1 0 -2.31z",
  },
};

window.customIcons ??= {};
window.customIcons.notification_journal = {
  getIcon: async (name) => (name in ICONS ? { ...ICONS[name], viewBox: "0 0 24 24" } : undefined),
  getIconList: async () => Object.keys(ICONS).map((name) => ({ name })),
};

export {};
