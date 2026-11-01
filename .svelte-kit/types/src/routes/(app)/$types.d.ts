import type * as Kit from '@sveltejs/kit';
import { MatcherParam } from '@sveltejs/kit/params';

type Expand<T> = T extends infer O ? { [K in keyof O]: O[K] } : never;
type RouteParams = {  };
type RouteId = '/(app)';
type MaybeWithVoid<T> = {} extends T ? T | void : T;
export type RequiredKeys<T> = { [K in keyof T]-?: {} extends { [P in K]: T[K] } ? never : K; }[keyof T];
type OutputDataShape<T> = MaybeWithVoid<Omit<App.PageData, RequiredKeys<T>> & Partial<Pick<App.PageData, keyof T & keyof App.PageData>> & Record<string, any>>
type EnsureDefined<T> = T extends null | undefined ? {} : T;
type OptionalUnion<U extends Record<string, any>, A extends keyof U = U extends U ? keyof U : never> = U extends unknown ? { [P in Exclude<A, keyof U>]?: never } & U : never;
/** @deprecated Use the `snapshot` helper from `$app/navigation` instead. */
export type Snapshot<T = any> = Kit.Snapshot<T>;
export type ErrorProps = { error: App.Error };
type PageParentData = Omit<EnsureDefined<import('../$types.js').LayoutData>, keyof LayoutData> & EnsureDefined<LayoutData>;
type LayoutRouteId = RouteId | "/(app)" | "/(app)/admin" | "/(app)/admin/analytics" | "/(app)/admin/analytics/[tab]" | "/(app)/admin/evaluations" | "/(app)/admin/evaluations/[tab]" | "/(app)/admin/functions" | "/(app)/admin/functions/create" | "/(app)/admin/functions/edit" | "/(app)/admin/settings" | "/(app)/admin/settings/[tab]" | "/(app)/admin/users" | "/(app)/admin/users/[tab]" | "/(app)/automations" | "/(app)/automations/[id]" | "/(app)/c/[id]" | "/(app)/calendar" | "/(app)/channels/[id]" | "/(app)/coder" | "/(app)/home" | "/(app)/notes" | "/(app)/notes/[id]" | "/(app)/notes/new" | "/(app)/playground" | "/(app)/playground/completions" | "/(app)/playground/images" | "/(app)/studio" | "/(app)/workspace" | "/(app)/workspace/functions/create" | "/(app)/workspace/knowledge" | "/(app)/workspace/knowledge/[id]" | "/(app)/workspace/knowledge/create" | "/(app)/workspace/models" | "/(app)/workspace/models/create" | "/(app)/workspace/models/edit" | "/(app)/workspace/prompts" | "/(app)/workspace/prompts/[id]" | "/(app)/workspace/prompts/create" | "/(app)/workspace/skills" | "/(app)/workspace/skills/create" | "/(app)/workspace/skills/edit" | "/(app)/workspace/tools" | "/(app)/workspace/tools/create" | "/(app)/workspace/tools/edit"
type LayoutParams = RouteParams & { tab?: string | undefined; id?: string | undefined }
type LayoutParentData = EnsureDefined<import('../$types.js').LayoutData>;

export type PageServerData = null;
export type PageData = Expand<PageParentData>;
export type PageProps = { params: RouteParams; data: PageData }
export type LayoutServerData = null;
export type LayoutData = Expand<LayoutParentData>;
export type LayoutProps = { params: LayoutParams; data: LayoutData; children: import("svelte").Snippet }