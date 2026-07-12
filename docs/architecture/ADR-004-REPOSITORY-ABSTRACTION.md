# ADR-004 — Repository Abstraction over storage & sync

- **Status:** Accepted (interfaces proposed; **not implemented in Phase 0**)
- **Date:** 2026-07-12

## Context
Presentation and app logic touch `localStorage` and Supabase directly (`save`,
`saveSettings`, `sync.js`, `metadata.js`). This couples UI to storage, blocks testing,
and hard-codes the local+cloud strategy.

## Decision
Introduce repository interfaces. The **first** implementations wrap today's exact
localStorage + Supabase behavior (a `LegacyLocalStore` and a `SupabaseSyncStore`),
proven equivalent by characterization tests **before** any call site is rewired. No
behavior changes when they land.

## Interfaces (signatures + responsibilities)

```ts
// Content (read-only; backed by the active content pack)
interface CardRepository {
  getById(id): Card | undefined;           // O(1) via prebuilt id-map
  all(): Card[];
  byLevel(level): Card[];
  levels(): string[];                       // ordered by levelOrder
  count(): number;
}
interface DeckRepository { list(): Deck[]; cardsIn(deckId): Card[]; }

// Per-user state
interface ProgressRepository {
  get(cardId): UserCardState;               // default when absent (due=today, zeros)
  put(cardId, state): void;                 // marks dirty for sync
  entries(): Record<id, UserCardState>;
  reset(): void;                            // clears local + cloud (existing reset)
}
interface SettingsRepository {
  get<T>(key, fallback): T;                 // safe defaults; unknown keys preserved
  set(key, value): void;                    // triggers settings sync (debounced)
  all(): Settings;
}
interface BookmarkRepository {
  isBookmarked(cardId): boolean;
  toggle(cardId): boolean; remove(cardId): void; list(): id[];
}
interface NoteRepository {
  get(cardId): string; has(cardId): boolean;
  set(cardId, text): void;                  // '' deletes; trims; ≤1000
}
interface AnalyticsRepository {
  recordStudyGrade(cardId, whenLocalDay): void;  // once/card/day
  dailyCounts(): Record<localDay, number>;
  weakness(state): number | null;           // deterministic weakness score
}
interface AuthRepository {
  currentUser(): {id, username} | null;
  isLoggedIn(): boolean;
  accessToken(): Promise<string>;           // refresh if near expiry
  login(username, pin): Promise<User>; register(username, pin): Promise<User>;
  logout(): void; changePin(oldPin, newPin): Promise<void>; deleteAccount(pin): Promise<void>;
}
```

## Rules
- Domain/use-cases depend only on these **interfaces**, never on `localStorage`,
  `fetch`, or Supabase directly.
- `ProgressRepository.put` and `SettingsRepository.set` are the only write paths that
  enqueue sync; the sync engine owns dirty-set + debounce + latest-wins (`SYNC_CONTRACT.md`).
- Repositories are account-scoped by construction (namespace injected once).

## Consequences
- Enables unit/characterization testing of the domain without a browser or backend.
- Local-only vs cloud becomes a composition choice (which store backs the repos),
  not scattered `if(window.HSKSync)` guards.
