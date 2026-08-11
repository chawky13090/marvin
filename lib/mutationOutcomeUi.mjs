import { isMutationOutcomeUnknown } from './backendFallback.mjs';

export function reportMutationFailure(toast, error, {
  action,
  fallbackMessage,
  onVerify,
  verifyLabel = 'Vérifier maintenant',
}) {
  if (isMutationOutcomeUnknown(error)) {
    toast.warning(
      'Résultat non confirmé',
      `${action} a peut-être abouti. Marvin ne l’a pas relancée automatiquement. Vérifiez l’état avant toute nouvelle tentative.`,
      {
        duration: 12000,
        actionLabel: onVerify ? verifyLabel : undefined,
        onAction: onVerify,
      },
    );
    return;
  }
  toast.error(`${action} impossible`, fallbackMessage);
}
