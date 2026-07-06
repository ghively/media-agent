/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#08090a',
        panel: '#0f1011',
        surface: '#191a1b',
        hover: '#28282c',
        ink: {
          DEFAULT: '#f7f8f8',
          secondary: '#d0d6e0',
          muted: '#8a8f98',
          subtle: '#62666d',
        },
        accent: {
          DEFAULT: '#5e6ad2',
          hover: '#828fff',
        },
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#f85149',
        border: {
          subtle: 'rgba(255,255,255,0.05)',
          DEFAULT: 'rgba(255,255,255,0.08)',
          strong: '#34343a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        'display': ['48px', { lineHeight: '1', letterSpacing: '-1.056px', fontWeight: '510' }],
        'heading': ['24px', { lineHeight: '1.33', letterSpacing: '-0.288px', fontWeight: '400' }],
        'title': ['20px', { lineHeight: '1.33', letterSpacing: '-0.24px', fontWeight: '590' }],
        'body-lg': ['18px', { lineHeight: '1.6', letterSpacing: '-0.165px' }],
        'body': ['16px', { lineHeight: '1.5' }],
        'caption': ['13px', { lineHeight: '1.5', letterSpacing: '-0.13px' }],
        'label': ['12px', { lineHeight: '1.4' }],
        'micro': ['11px', { lineHeight: '1.4' }],
      },
      animation: {
        'slide-up': 'slideUp 0.3s ease-out',
        'status-pulse': 'statusPulse 3s ease-in-out infinite',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        statusPulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
      },
    },
  },
  plugins: [],
}
