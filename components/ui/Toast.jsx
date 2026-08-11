'use client';

import { createContext, useContext, useState, useCallback, useMemo, useRef, useEffect } from 'react';

const ToastContext = createContext(null);

let toastId = 0;

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast doit être utilisé dans un ToastProvider');
  }
  return context;
}

const ICONS = {
  success: '✅',
  error: '❌',
  warning: '⚠️',
  info: 'ℹ️',
};

function ToastItem({ toast, onClose }) {
  const [exiting, setExiting] = useState(false);

  const handleClose = useCallback(() => {
    setExiting(true);
    setTimeout(() => onClose(toast.id), 280);
  }, [onClose, toast.id]);

  const handleAction = useCallback(() => {
    try {
      toast.onAction?.();
    } finally {
      handleClose();
    }
  }, [handleClose, toast]);

  useAutoClose(toast.duration || 4000, handleClose);

  return (
    <div
      className={`toast toast-${toast.type} ${exiting ? 'toast-exiting' : ''}`}
      role="alert"
    >
      <span className="toast-icon">{ICONS[toast.type] || ICONS.info}</span>
      <div className="toast-body">
        {toast.title && <div className="toast-title">{toast.title}</div>}
        {toast.message && <div className="toast-message">{toast.message}</div>}
        {toast.actionLabel && toast.onAction && (
          <button className="toast-action" type="button" onClick={handleAction}>
            {toast.actionLabel}
          </button>
        )}
      </div>
      <button className="toast-close" onClick={handleClose} aria-label="Fermer">
        ✕
      </button>
    </div>
  );
}

function useAutoClose(delay, callback) {
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    const timer = setTimeout(() => callbackRef.current(), delay);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback(({ type = 'info', title, message, duration, actionLabel, onAction }) => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, type, title, message, duration, actionLabel, onAction }]);
    return id;
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useMemo(
    () => ({
      success: (title, message, options = {}) => addToast({ ...options, type: 'success', title, message }),
      error: (title, message, options = {}) => addToast({ ...options, type: 'error', title, message }),
      warning: (title, message, options = {}) => addToast({ ...options, type: 'warning', title, message }),
      info: (title, message, options = {}) => addToast({ ...options, type: 'info', title, message }),
    }),
    [addToast]
  );

  // We wrap the object manually since useMemo is better here
  const contextValue = { addToast, removeToast, toast };

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <div className="toast-container">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onClose={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
