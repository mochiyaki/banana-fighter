// Crowd skins + lieutenant / boss models registry (content for the crowd view's hook, src/crowd/view.js header). The
// stage picks skins with `skin: { foe, ally }` (story/chapters.js); officers with `model: key` in their OFF entry. New
// skins / models register here with one import + one entry.
import { BLACKHAT, WHITEHAT } from './skins.js';
import { SYSOP, PHISH, TROJAN, RANSOM, ROOT, ROOT_UNMASKED, FORK } from './models.js';

export const SKINS = { blackhat: BLACKHAT, whitehat: WHITEHAT };
export const OFFICER_MODELS = { sysop: SYSOP, phish: PHISH, trojan: TROJAN, ransom: RANSOM, root: ROOT, root_unmasked: ROOT_UNMASKED, fork: FORK };
