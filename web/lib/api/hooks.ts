"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export function useApiQuery<TData, TDto = TData>(queryKey: readonly unknown[], path: string, adapt?: (dto: TDto) => TData) {
  return useQuery({
    queryKey,
    queryFn: async () => {
      const dto = await api.get<TDto>(path);
      return adapt ? adapt(dto) : dto as unknown as TData;
    },
    staleTime: 30_000,
    retry: 1,
  });
}

export function useApiMutation<TData, TVariables>(path: string, invalidateKey: readonly unknown[], method: "post" | "patch" = "post") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: TVariables) => api[method]<TData>(path, variables),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invalidateKey }),
  });
}
