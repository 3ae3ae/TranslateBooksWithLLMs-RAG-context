import { h, Fragment, render } from '../../vendor/preact.mjs';
import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from '../../vendor/preact-hooks.mjs';
import { signal, computed, effect, batch, useSignal, useComputed, useSignalEffect } from '../../vendor/signals.mjs';
import htm from '../../vendor/htm.mjs';

export const html = htm.bind(h);
export {
  h, Fragment, render,
  useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback,
  signal, computed, effect, batch, useSignal, useComputed, useSignalEffect,
};

let idCounter = 0;
/** Stable unique id for label/aria wiring. */
export function useUid(prefix = 'uid') {
  const ref = useRef(null);
  if (ref.current === null) ref.current = `${prefix}-${++idCounter}`;
  return ref.current;
}

/** Close a popover on outside pointer-down or Escape. */
export function useDismiss(open, onClose, ...refs) {
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (refs.some((r) => r.current && r.current.contains(e.target))) return;
      onClose();
    };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);
}

export const cx = (...parts) => parts.filter(Boolean).join(' ');
