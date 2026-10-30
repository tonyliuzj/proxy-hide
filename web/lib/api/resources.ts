"use client";

import { adaptAdminWorkspace, adaptDashboardSummary, adaptEndpoint, adaptFilter, adaptJob, adaptPage, adaptPool, adaptPoolListLink, adaptProxy, adaptSource, adaptTarget, adaptTrafficSummary, adaptWorkspaceSettings } from "@/lib/api/adapters";
import type { AdminQueueStatisticsDto, DashboardSummaryDto, EndpointDto, FilterDto, JobDto, PageDto, PoolDto, PoolListLinkDto, ProxyDto, SourceDto, TargetDto, TrafficSummaryDto, WorkspaceAdminDto, WorkspaceSettingsDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";
import type { AdminQueueStatistics, AdminWorkspace, DashboardSummary, Endpoint, JobRun, ListResponse, Pool, PoolListLink, ProxyFilter, ProxyRecord, Source, Target, TrafficSummary, WorkspaceSettings } from "@/lib/api/types";
import { buildQuery } from "@/lib/api/client";

type Params = Record<string, string | number | boolean | undefined>;

export const useProxies = (params: Params = {}) => useApiQuery<ListResponse<ProxyRecord>, PageDto<ProxyDto>>(["proxies", params], `/proxies${buildQuery(params)}`, (page) => adaptPage(page, adaptProxy));
export const useSources = (params: Params = {}) => useApiQuery<ListResponse<Source>, PageDto<SourceDto>>(["sources", params], `/sources${buildQuery(params)}`, (page) => adaptPage(page, adaptSource));
export const useTargets = (params: Params = {}) => useApiQuery<ListResponse<Target>, PageDto<TargetDto>>(["targets", params], `/targets${buildQuery(params)}`, (page) => adaptPage(page, adaptTarget));
export const useFilters = (params: Params = {}) => useApiQuery<ListResponse<ProxyFilter>, PageDto<FilterDto>>(["filters", params], `/filters${buildQuery(params)}`, (page) => adaptPage(page, adaptFilter));
export const usePools = (params: Params = {}) => useApiQuery<ListResponse<Pool>, PageDto<PoolDto>>(["pools", params], `/pools${buildQuery(params)}`, (page) => adaptPage(page, adaptPool));
export const usePoolListLinks = (poolId: string) => useApiQuery<PoolListLink[], PoolListLinkDto[]>(["pool-list-links", poolId], `/pools/${poolId}/list-links`, (links) => links.map(adaptPoolListLink));
export const useEndpoints = (params: Params = {}) => useApiQuery<ListResponse<Endpoint>, PageDto<EndpointDto>>(["endpoints", params], `/endpoints${buildQuery(params)}`, (page) => adaptPage(page, adaptEndpoint));
export const useJobs = (params: Params = {}) => useApiQuery<ListResponse<JobRun>, PageDto<JobDto>>(["checks", params], `/checks${buildQuery(params)}`, (page) => adaptPage(page, adaptJob));
export const useAdminWorkspaces = (params: Params = {}) => useApiQuery<ListResponse<AdminWorkspace>, PageDto<WorkspaceAdminDto>>(["admin", "workspaces", params], `/admin/workspaces${buildQuery(params)}`, (page) => adaptPage(page, adaptAdminWorkspace));
export const useAdminWorkspace = (workspaceId: string) => useApiQuery<AdminWorkspace, WorkspaceAdminDto>(["admin", "workspaces", workspaceId], `/admin/workspaces/${workspaceId}`, adaptAdminWorkspace);
export const useAdminWorkspaceProxies = (workspaceId: string, params: Params = {}) => useApiQuery<ListResponse<ProxyRecord>, PageDto<ProxyDto>>(["admin", "workspaces", workspaceId, "proxies", params], `/admin/workspaces/${workspaceId}/proxies${buildQuery(params)}`, (page) => adaptPage(page, adaptProxy));
export const useAdminWorkspaceGlobalPools = (workspaceId: string, params: Params = {}) => useApiQuery<ListResponse<Pool>, PageDto<PoolDto>>(["admin", "workspaces", workspaceId, "global-pools", params], `/admin/workspaces/${workspaceId}/global-pools${buildQuery(params)}`, (page) => adaptPage(page, adaptPool));
export const useDashboardSummary = () => useApiQuery<DashboardSummary, DashboardSummaryDto>(["dashboard"], "/dashboard", adaptDashboardSummary);
export const useTraffic = (params: Params = {}) => useApiQuery<TrafficSummary, TrafficSummaryDto>(["traffic", params], `/traffic${buildQuery(params)}`, adaptTrafficSummary);
export const useWorkspaceSettings = () => useApiQuery<WorkspaceSettings, WorkspaceSettingsDto>(["settings"], "/settings", adaptWorkspaceSettings);
export const useAdminProxies = (params: Params = {}) => useApiQuery<ListResponse<ProxyRecord>, PageDto<ProxyDto>>(["admin", "proxies", params], `/admin/proxies${buildQuery(params)}`, (page) => adaptPage(page, adaptProxy));
export const useAdminSources = (params: Params = {}) => useApiQuery<ListResponse<Source>, PageDto<SourceDto>>(["admin", "sources", params], `/admin/sources${buildQuery(params)}`, (page) => adaptPage(page, (source) => ({ ...adaptSource(source), scope: "global" })));
export const useAdminQueue = () => useApiQuery<AdminQueueStatistics, AdminQueueStatisticsDto>(["admin", "checks", "queue"], "/admin/checks/queue", (data) => ({ queued: data.queued, running: data.running, total: data.total, items: data.items.map((job) => ({ ...adaptJob(job), workspaceId: job.workspace_id ?? undefined })) }));
