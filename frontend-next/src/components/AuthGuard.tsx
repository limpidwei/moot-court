"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

interface AuthGuardProps {
  children: React.ReactNode;
}

export default function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const pathname = usePathname();
  // P4 修复：useEffect 异步触发导致首次渲染先展示受保护页面再跳转登录（"flash"）。
  // 改为：公开页直接渲染，受保护页首次返回 null，useEffect 验证通过后再展示 children。
  const [authorized, setAuthorized] = useState(false);
  const publicPaths = ["/auth/login", "/auth/register"];
  const isPublic = publicPaths.includes(pathname);

  useEffect(() => {
    if (isPublic || isAuthenticated()) {
      setAuthorized(true);
    } else {
      router.push("/auth/login");
    }
  }, [pathname, router, isPublic]);

  // 公开页或已验证 → 渲染；未验证的受保护页 → null（无 flash）
  if (!isPublic && !authorized) return null;

  return <>{children}</>;
}
