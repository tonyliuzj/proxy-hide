import { expect, test } from "@playwright/test";

async function signIn(page: import("@playwright/test").Page, admin = false) {
  await page.goto("/login");
  if (admin) await page.getByLabel("Email").fill("ops@proxyhide.io");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(admin ? /\/admin$/ : /\/dashboard$/);
}

async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("workspace owner imports proxies and publishes one-time endpoint credentials", async ({ page }) => {
  await signIn(page);

  await page.goto("/proxies");
  await page.getByRole("button", { name: "Import proxies" }).click();
  await page.getByLabel("Proxy list").fill("185.44.72.19:3128\nsocks5://user:password@51.89.12.204:1080");
  await page.getByRole("button", { name: "Preview import" }).click();
  await expect(page.getByText("Valid", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Import 2" }).click();
  await expect(page.getByText("2 proxies queued for initial checks")).toBeVisible();

  await page.goto("/endpoints");
  await page.getByRole("button", { name: "Publish endpoint" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Google UK customer");
  await page.getByRole("combobox").nth(0).click();
  await page.getByRole("option").first().click();
  await page.getByRole("combobox").nth(1).click();
  await page.getByRole("option", { name: /username and secret/ }).click();
  await page.getByLabel("Gateway username").fill("google-uk-customer");
  await page.getByRole("button", { name: "Publish endpoint" }).last().click();
  await expect(page.getByRole("heading", { name: "Endpoint credentials" })).toBeVisible();
  await expect(page.getByText(/https:\/\/google-uk-customer:/)).toBeVisible();
  await expect(page.getByText(/http:\/\/google-uk-customer:/)).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("platform admin provisions a workspace with operator limits", async ({ page }) => {
  await signIn(page, true);
  await page.goto("/admin/workspaces");
  await page.getByRole("button", { name: "Create workspace" }).click();
  const dialog = page.getByRole("dialog");
  const inputs = dialog.locator("input");
  await inputs.nth(0).fill("Acme Search");
  await inputs.nth(1).fill("acme-search");
  await inputs.nth(2).fill("owner@acme.example");
  await inputs.nth(3).fill("permanent-password-2026");
  await dialog.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByText("Workspace provisioned")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("all workspace and admin views fit the viewport", async ({ page }) => {
  const workspaceRoutes = ["/dashboard", "/proxies", "/sources", "/targets", "/filters", "/pools", "/endpoints", "/checks", "/traffic", "/settings"];
  for (const route of workspaceRoutes) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
  for (const route of ["/admin", "/admin/workspaces", "/admin/catalog"]) {
    await page.goto(route);
    await expect(page.locator("h1")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});
