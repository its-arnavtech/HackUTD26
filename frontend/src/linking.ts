// Whether the customer linked an account on the consent screen, for this browser session only.
// The demo starts linked to the fixture account (design lab behavior). A17 can move this to the API.
const KEY = "sentinel-linked";

export function isLinked(): boolean {
  try {
    return sessionStorage.getItem(KEY) !== "false";
  } catch {
    return true;
  }
}

export function setLinked(linked: boolean): void {
  try {
    sessionStorage.setItem(KEY, String(linked));
  } catch {
    // Storage blocked: the demo stays on its default.
  }
}
