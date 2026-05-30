/** @type {import('tailwindcss').Config} */
//
// Colors use the CSS relative-color syntax so Tailwind opacity modifiers
// (e.g. `bg-primary/90`, `ring-ring/50`) substitute into the alpha channel.
// tokens.css keeps the canonical oklch() value per token; here we re-emit it
// with `<alpha-value>` so Tailwind can interpolate opacity.
const alpha = (v) => `oklch(from var(${v}) l c h / <alpha-value>)`;

module.exports = {
  content: [
    "./templates/**/*.html",
    "./src/**/*.py",
    "./static/js/**/*.js",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        border:       alpha("--border"),
        input:        alpha("--input"),
        ring:         alpha("--ring"),
        background:   alpha("--background"),
        foreground:   alpha("--foreground"),
        primary: {
          DEFAULT:    alpha("--primary"),
          foreground: alpha("--primary-foreground"),
        },
        secondary: {
          DEFAULT:    alpha("--secondary"),
          foreground: alpha("--secondary-foreground"),
        },
        muted: {
          DEFAULT:    alpha("--muted"),
          foreground: alpha("--muted-foreground"),
        },
        accent: {
          DEFAULT:    alpha("--accent"),
          foreground: alpha("--accent-foreground"),
        },
        destructive: {
          DEFAULT:    alpha("--destructive"),
          foreground: alpha("--destructive-foreground"),
        },
        card: {
          DEFAULT:    alpha("--card"),
          foreground: alpha("--card-foreground"),
        },
        popover: {
          DEFAULT:    alpha("--popover"),
          foreground: alpha("--popover-foreground"),
        },
        sidebar: {
          DEFAULT:    alpha("--sidebar"),
          foreground: alpha("--sidebar-foreground"),
          primary: {
            DEFAULT:  alpha("--sidebar-primary"),
            foreground: alpha("--sidebar-primary-foreground"),
          },
          accent: {
            DEFAULT:  alpha("--sidebar-accent"),
            foreground: alpha("--sidebar-accent-foreground"),
          },
          border:     alpha("--sidebar-border"),
          ring:       alpha("--sidebar-ring"),
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: [
          "Geist",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["Geist Mono", "JetBrains Mono", "Menlo", "Monaco", "monospace"],
      },
    },
  },
  plugins: [],
};
