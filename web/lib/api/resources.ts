"use client";

import { adaptAdminWorkspace, adaptDashboardSummary, adaptEndpoint, adaptFilter, adaptJob, adaptPage, adaptPool, adaptProxy, adaptSource, adaptTarget, adaptTrafficSummary, adaptWorkspaceSettings } from "@/lib/api/adapters";
import type { DashboardSummaryDto, EndpointDto, FilterDto, JobDto, PageDto, PoolDto, ProxyDto, SourceDto, TargetDto, TrafficSummaryDto, WorkspaceAdminDto, WorkspaceSettingsDto } from "@/lib/api/dto";
import { useApiQuery } from "@/lib/api/hooks";
import type { AdminWorkspace, DashboardSummary, Endpoint, JobRun, ListResponse, Pool, ProxyFilter, ProxyRecord, Source, Target, TrafficSummary, WorkspaceSettings } from "@/lib/api/types";
import { buildQuery } from "@/lib/api/client";

type Params = Record<string, string | number | boolean | undefined>;

export const useProxies = (params: Params = {}) => useApiQuery<ListResponse<ProxyRecord>, PageDto<ProxyDto>>(["proxies", params], `/proxies${buildQuery(params)}`, (page) => adaptPage(page, adaptProxy));
export const useSources = (params: Params = {}) => useApiQuery<ListResponse<Source>, PageDto<SourceDto>>(["sources", params], `/sources${buildQuery(params)}`, (page) => adaptPage(page, adaptSource));
export const useTargets = (params: Params = {}) => useApiQuery<ListResponse<Target>, PageDto<TargetDto>>(["targets", params], `/targets${buildQuery(params)}`, (page) => adaptPage(page, adaptTarget));
export const useFilters = (params: Params = {}) => useApiQuery<ListResponse<ProxyFilter>, PageDto<FilterDto>>(["filters", params], `/filters${buildQuery(params)}`, (page) => adaptPage(page, adaptFilter));
export const usePools = (params: Params = {}) => useApiQuery<ListResponse<Pool>, PageDto<PoolDto>>(["pools", params], `/pools${buildQuery(params)}`, (page) => adaptPage(page, adaptPool));
export const useEndpoints = (params: Params = {}) => useApiQuery<ListResponse<Endpoint>, PageDto<EndpointDto>>(["endpoints", params], `/endpoints${buildQuery(params)}`, (page) => adaptPage(page, adaptEndpoint));
export const useJobs = (params: Params = {}) => useApiQuery<ListResponse<JobRun>, PageDto<JobDto>>(["checks", params], `/checks${buildQuery(params)}`, (page) => adaptPage(page, adaptJob));
export const useAdminWorkspaces = (params: Params = {}) => useApiQuery<ListResponse<AdminWorkspace>, PageDto<WorkspaceAdminDto>>(["admin", "workspaces", params], `/admin/workspaces${buildQuery(params)}`, (page) => adaptPage(page, adaptAdminWorkspace));
export const useDashboardSummary = () => useApiQuery<DashboardSummary, DashboardSummaryDto>(["dashboard"], "/dashboard", adaptDashboardSummary);
export const useTraffic = (params: Params = {}) => useApiQuery<TrafficSummary, TrafficSummaryDto>(["traffic", params], `/traffic${buildQuery(params)}`, adaptTrafficSummary);
export const useWorkspaceSettings = () => useApiQuery<WorkspaceSettings, WorkspaceSettingsDto>(["settings"], "/settings", adaptWorkspaceSettings);
export const useAdminProxies = (params: Params = {}) => useApiQuery<ListResponse<ProxyRecord>, PageDto<ProxyDto>>(["admin", "proxies", params], `/admin/proxies${buildQuery(params)}`, (page) => adaptPage(page, adaptProxy));
export const useAdminSources = (params: Params = {}) => useApiQuery<ListResponse<Source>, PageDto<SourceDto>>(["admin", "sources", params], `/admin/sources${buildQuery(params)}`, (page) => adaptPage(page, (source) => ({ ...adaptSource(source), scope: "global" })));
