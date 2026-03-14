/**
 * Theme definitions for Gaius landing page
 *
 * Themes ported from Cloudera Cybersec project.
 * Configurable via HOCON or KV storage.
 *
 * Each theme provides:
 * - colors: CSS color values
 * - effects: CSS shadow/glow effects
 * - three: Three.js hex colors for 3D viz
 */

export interface ThemeMeta {
  name: string;
  author: string;
  url: string;
}

export interface ThemeColors {
  // Accent colors
  amber: string;
  gold: string;
  bronze: string;
  // Background colors
  void: string;      // Deepest background
  charcoal: string;  // Card background
  containment: string;
  grid: string;
  // Semantic colors
  success: string;
  info: string;
  warning: string;
  error: string;
  // Text colors
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  textTerminal: string;
}

export interface ThemeEffects {
  glowAmber: string;
  glowSuccess: string;
  shadowCard: string;
}

export interface ThreeColors {
  fog: number;
  gridPrimary: number;
  gridSecondary: number;
  ambientLight: number;
  directionalLight: number;
  pointLight1: number;
  pointLight2: number;
  blockBase: number;
  blockSpecular: number;
}

export interface Theme {
  id: string;
  meta: ThemeMeta;
  colors: ThemeColors;
  effects: ThemeEffects;
  three: ThreeColors;
}

// ============================================================================
// Theme Definitions
// ============================================================================

export const KEIRETSU_DARK: Theme = {
  id: 'keiretsu-dark',
  meta: {
    name: 'Keiretsu Dark',
    author: 'Cybersec Project',
    url: 'https://github.com/rch/cldr-cybersec',
  },
  colors: {
    amber: '#D4A84B',
    gold: '#FFD700',
    bronze: '#CD853F',
    void: '#0A0A0F',
    charcoal: '#12121A',
    containment: '#1A1A24',
    grid: '#252532',
    success: '#00FF88',
    info: '#00FFFF',
    warning: '#FFB347',
    error: '#FF4444',
    textPrimary: '#E8E8F0',
    textSecondary: '#A0A0B0',
    textMuted: '#606070',
    textTerminal: '#00FF88',
  },
  effects: {
    glowAmber: '0 0 20px rgba(212, 168, 75, 0.3)',
    glowSuccess: '0 0 10px rgba(0, 255, 136, 0.4)',
    shadowCard: '0 4px 20px rgba(0, 0, 0, 0.4)',
  },
  three: {
    fog: 0x0a0a0f,
    gridPrimary: 0xd4a84b,
    gridSecondary: 0x252532,
    ambientLight: 0x202030,
    directionalLight: 0xd4a84b,
    pointLight1: 0x00ff88,
    pointLight2: 0x00ffff,
    blockBase: 0x12121a,
    blockSpecular: 0xd4a84b,
  },
};

export const SOLARIZED_DARK: Theme = {
  id: 'solarized-dark',
  meta: {
    name: 'Solarized Dark',
    author: 'Ethan Schoonover',
    url: 'https://ethanschoonover.com/solarized/',
  },
  colors: {
    amber: '#b58900',
    gold: '#b58900',
    bronze: '#cb4b16',
    void: '#002b36',
    charcoal: '#073642',
    containment: '#073642',
    grid: '#586e75',
    success: '#859900',
    info: '#2aa198',
    warning: '#cb4b16',
    error: '#dc322f',
    textPrimary: '#839496',
    textSecondary: '#657b83',
    textMuted: '#586e75',
    textTerminal: '#859900',
  },
  effects: {
    glowAmber: 'none',
    glowSuccess: 'none',
    shadowCard: '0 2px 8px rgba(0, 0, 0, 0.3)',
  },
  three: {
    fog: 0x002b36,
    gridPrimary: 0xb58900,
    gridSecondary: 0x586e75,
    ambientLight: 0x073642,
    directionalLight: 0xb58900,
    pointLight1: 0x859900,
    pointLight2: 0x2aa198,
    blockBase: 0x073642,
    blockSpecular: 0xb58900,
  },
};

export const SOLARIZED_LIGHT: Theme = {
  id: 'solarized-light',
  meta: {
    name: 'Solarized Light',
    author: 'Ethan Schoonover',
    url: 'https://ethanschoonover.com/solarized/',
  },
  colors: {
    amber: '#b58900',
    gold: '#b58900',
    bronze: '#cb4b16',
    void: '#fdf6e3',
    charcoal: '#eee8d5',
    containment: '#eee8d5',
    grid: '#93a1a1',
    success: '#859900',
    info: '#2aa198',
    warning: '#cb4b16',
    error: '#dc322f',
    textPrimary: '#657b83',
    textSecondary: '#839496',
    textMuted: '#93a1a1',
    textTerminal: '#859900',
  },
  effects: {
    glowAmber: 'none',
    glowSuccess: 'none',
    shadowCard: '0 2px 8px rgba(0, 0, 0, 0.1)',
  },
  three: {
    fog: 0xfdf6e3,
    gridPrimary: 0xb58900,
    gridSecondary: 0x93a1a1,
    ambientLight: 0xeee8d5,
    directionalLight: 0xb58900,
    pointLight1: 0x859900,
    pointLight2: 0x2aa198,
    blockBase: 0xeee8d5,
    blockSpecular: 0xb58900,
  },
};

export const DRACULA: Theme = {
  id: 'dracula',
  meta: {
    name: 'Dracula',
    author: 'Zeno Rocha',
    url: 'https://draculatheme.com/',
  },
  colors: {
    amber: '#ffb86c',
    gold: '#f1fa8c',
    bronze: '#ff79c6',
    void: '#282a36',
    charcoal: '#21222c',
    containment: '#343746',
    grid: '#44475a',
    success: '#50fa7b',
    info: '#8be9fd',
    warning: '#ffb86c',
    error: '#ff5555',
    textPrimary: '#f8f8f2',
    textSecondary: '#bfbfbf',
    textMuted: '#6272a4',
    textTerminal: '#50fa7b',
  },
  effects: {
    glowAmber: '0 0 10px rgba(255, 184, 108, 0.3)',
    glowSuccess: '0 0 10px rgba(80, 250, 123, 0.3)',
    shadowCard: '0 4px 16px rgba(0, 0, 0, 0.4)',
  },
  three: {
    fog: 0x282a36,
    gridPrimary: 0xffb86c,
    gridSecondary: 0x44475a,
    ambientLight: 0x21222c,
    directionalLight: 0xffb86c,
    pointLight1: 0x50fa7b,
    pointLight2: 0x8be9fd,
    blockBase: 0x21222c,
    blockSpecular: 0xffb86c,
  },
};

export const NORD: Theme = {
  id: 'nord',
  meta: {
    name: 'Nord',
    author: 'Arctic Ice Studio',
    url: 'https://www.nordtheme.com/',
  },
  colors: {
    amber: '#ebcb8b',
    gold: '#ebcb8b',
    bronze: '#d08770',
    void: '#2e3440',
    charcoal: '#3b4252',
    containment: '#434c5e',
    grid: '#4c566a',
    success: '#a3be8c',
    info: '#88c0d0',
    warning: '#ebcb8b',
    error: '#bf616a',
    textPrimary: '#eceff4',
    textSecondary: '#d8dee9',
    textMuted: '#4c566a',
    textTerminal: '#a3be8c',
  },
  effects: {
    glowAmber: 'none',
    glowSuccess: 'none',
    shadowCard: '0 2px 12px rgba(0, 0, 0, 0.25)',
  },
  three: {
    fog: 0x2e3440,
    gridPrimary: 0x88c0d0,
    gridSecondary: 0x4c566a,
    ambientLight: 0x3b4252,
    directionalLight: 0x88c0d0,
    pointLight1: 0xa3be8c,
    pointLight2: 0x81a1c1,
    blockBase: 0x3b4252,
    blockSpecular: 0x88c0d0,
  },
};

export const GRUVBOX_DARK: Theme = {
  id: 'gruvbox-dark',
  meta: {
    name: 'Gruvbox Dark',
    author: 'Pavel Pertsev',
    url: 'https://github.com/morhetz/gruvbox',
  },
  colors: {
    amber: '#fe8019',
    gold: '#fabd2f',
    bronze: '#d65d0e',
    void: '#282828',
    charcoal: '#1d2021',
    containment: '#3c3836',
    grid: '#504945',
    success: '#b8bb26',
    info: '#83a598',
    warning: '#fe8019',
    error: '#fb4934',
    textPrimary: '#ebdbb2',
    textSecondary: '#d5c4a1',
    textMuted: '#665c54',
    textTerminal: '#b8bb26',
  },
  effects: {
    glowAmber: '0 0 10px rgba(254, 128, 25, 0.25)',
    glowSuccess: '0 0 10px rgba(184, 187, 38, 0.25)',
    shadowCard: '0 3px 12px rgba(0, 0, 0, 0.35)',
  },
  three: {
    fog: 0x282828,
    gridPrimary: 0xfe8019,
    gridSecondary: 0x504945,
    ambientLight: 0x1d2021,
    directionalLight: 0xfe8019,
    pointLight1: 0xb8bb26,
    pointLight2: 0x83a598,
    blockBase: 0x1d2021,
    blockSpecular: 0xfe8019,
  },
};

// ============================================================================
// Theme Registry
// ============================================================================

export const THEMES: Record<string, Theme> = {
  'keiretsu-dark': KEIRETSU_DARK,
  'solarized-dark': SOLARIZED_DARK,
  'solarized-light': SOLARIZED_LIGHT,
  'dracula': DRACULA,
  'nord': NORD,
  'gruvbox-dark': GRUVBOX_DARK,
};

export const DEFAULT_THEME_ID = 'keiretsu-dark';

/**
 * Get theme by ID with fallback to default
 */
export function getTheme(id: string | null | undefined): Theme {
  if (id && THEMES[id]) {
    return THEMES[id];
  }
  return THEMES[DEFAULT_THEME_ID];
}

/**
 * List available theme IDs and names
 */
export function listThemes(): Array<{ id: string; name: string }> {
  return Object.entries(THEMES).map(([id, theme]) => ({
    id,
    name: theme.meta.name,
  }));
}

/**
 * Generate CSS variables from theme
 */
export function generateCSSVariables(theme: Theme): string {
  return `
    :root {
      /* Accent colors */
      --color-amber: ${theme.colors.amber};
      --color-gold: ${theme.colors.gold};
      --color-bronze: ${theme.colors.bronze};

      /* Background colors */
      --color-void: ${theme.colors.void};
      --color-charcoal: ${theme.colors.charcoal};
      --color-containment: ${theme.colors.containment};
      --color-grid: ${theme.colors.grid};

      /* Semantic colors */
      --color-success: ${theme.colors.success};
      --color-info: ${theme.colors.info};
      --color-warning: ${theme.colors.warning};
      --color-error: ${theme.colors.error};

      /* Text colors */
      --text-primary: ${theme.colors.textPrimary};
      --text-secondary: ${theme.colors.textSecondary};
      --text-muted: ${theme.colors.textMuted};
      --text-terminal: ${theme.colors.textTerminal};

      /* Effects */
      --glow-amber: ${theme.effects.glowAmber};
      --glow-success: ${theme.effects.glowSuccess};
      --shadow-card: ${theme.effects.shadowCard};
    }
  `;
}
