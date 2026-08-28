import type { JSX } from 'preact';

declare module 'preact' {
  namespace JSX {
    interface IntrinsicElements {
      'wa-drawer': JSX.HTMLAttributes<HTMLElement> & {
        open?: boolean;
        label?: string;
        placement?: 'top' | 'end' | 'bottom' | 'start';
        'light-dismiss'?: boolean;
      };
    }
  }
}
