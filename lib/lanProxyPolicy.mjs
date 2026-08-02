export function decideLanProxy(result) {
  if (result?.authenticated === true && result?.authorized === true) return 'allow';
  if (result?.authenticated === true) return 'forbid';
  return 'authenticate';
}
