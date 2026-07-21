import { expect, test } from '@playwright/test'

const backendOrigin = 'http://127.0.0.1:8011'
const paperId = 'anomaly-transformer-2022'

test('authorized_local_pdf: MySQL, private preview, and Neo4j close the paper-reading loop', async ({ page, request }) => {
  const health = await request.get(`${backendOrigin}/api/v1/healthz`)
  expect(health.ok()).toBeTruthy()

  const readinessResponse = await request.get(`${backendOrigin}/api/v1/demo/readiness`)
  expect(readinessResponse.ok()).toBeTruthy()
  const readiness = await readinessResponse.json()
  expect(readiness).toMatchObject({
    status: 'ready',
    runtime_mode: 'local_infrastructure',
  })
  const readinessChecks = Object.fromEntries(
    readiness.checks.map((item: { check_id: string; status: string }) => [item.check_id, item.status]),
  )
  expect(readinessChecks).toMatchObject({
    document_structure: 'ready',
    private_pdf_preview: 'ready',
    evidence_graph: 'ready',
    assistant_backend: 'ready',
  })

  const structureResponse = await request.get(
    `${backendOrigin}/api/v1/papers/${paperId}/document-structure`,
  )
  expect(structureResponse.ok()).toBeTruthy()
  const structure = await structureResponse.json()
  expect(structure).toMatchObject({
    source: 'parsed_pdf',
    parser_name: 'pymupdf',
    page_count: 20,
  })
  expect(structure.file_sha256).toMatch(/^[a-f0-9]{64}$/)
  expect(structure.sections).toHaveLength(28)
  const figureOne = structure.artifacts.find(
    (item: { label: string }) => item.label === 'Figure 1',
  )
  expect(figureOne).toMatchObject({ id: 'art-1', page: 4 })

  const graphResponse = await request.get(
    `${backendOrigin}/api/v1/papers/${paperId}/evidence-graph`,
  )
  expect(graphResponse.ok()).toBeTruthy()
  const graph = await graphResponse.json()
  expect(graph.source).toBe('neo4j')
  expect(graph.nodes).toHaveLength(30)
  expect(graph.edges).toHaveLength(65)

  const assistantSession = await request.post(`${backendOrigin}/api/v1/assistant/sessions`, {
    data: { paper_id: paperId },
  })
  expect(assistantSession.ok()).toBeTruthy()
  expect(await assistantSession.json()).toMatchObject({
    backend: 'offline',
    provider_status: 'ready',
  })

  for (const endpoint of [
    'document-preview/sections/sec-1',
    'document-preview/artifacts/art-1',
  ]) {
    const preview = await request.get(`${backendOrigin}/api/v1/papers/${paperId}/${endpoint}`)
    expect(preview.ok()).toBeTruthy()
    expect(preview.headers()['content-type']).toContain('image/png')
    expect(preview.headers()['cache-control']).toContain('private')
    expect(preview.headers()['cache-control']).toContain('no-store')
    expect(preview.headers()['x-kd-preview']).toBe('local-private-copy')
    const bytes = await preview.body()
    expect(bytes.subarray(1, 4).toString()).toBe('PNG')
  }
  const excerpt = await request.get(
    `${backendOrigin}/api/v1/papers/${paperId}/document-preview/artifacts/art-1/excerpt`,
  )
  expect(excerpt.ok()).toBeTruthy()
  expect(excerpt.headers()['x-kd-preview-scope']).toBe('derived-reading-excerpt')
  expect((await excerpt.body()).subarray(1, 4).toString()).toBe('PNG')

  await page.goto(`/papers/${paperId}`)
  await expect(page.getByTestId('paper-reader')).toBeVisible()
  await expect(page.getByText('API 在线 · 本地真实链路', { exact: true })).toBeVisible()
  await expect(page.getByTestId('reader-integrity')).toContainText('开发种子 · 未经双审')
  const status = page.getByTestId('core-service-status')
  await expect(status).toContainText('20 页')
  await expect(status).toContainText('10/10')
  await expect(status).toContainText('30/65')
  await expect(status).toContainText('neo4j')
  await expect(page.getByTestId('core-chain-stage')).toHaveCount(9)

  await page.getByTestId('demo-guide-toggle').click()
  const guide = page.getByTestId('demo-guide-panel')
  await expect(guide).toContainText('核心演示可用')
  await expect(guide).toContainText('本地真实基础设施')
  await expect(guide).toContainText('授权本地副本与MySQL中的SHA-256匹配')
  await expect(guide).toContainText('Neo4j真实返回30个节点和65条关系')
  await page.getByRole('button', { name: '关闭演示引导' }).click()

  const pdfImage = page.getByTestId('pdf-viewer-canvas').locator('img')
  await expect(pdfImage).toBeVisible()
  await expect.poll(() => pdfImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)
  expect(await pdfImage.evaluate((image: HTMLImageElement) => image.getBoundingClientRect().width)).toBeGreaterThanOrEqual(580)

  await page.getByRole('button', { name: '图表', exact: true }).click()
  await expect(page.getByTestId('artifact-preview-image')).toHaveCount(5)
  const figurePreview = page.locator('[data-testid="artifact-preview-image"][data-artifact-id="ar-1"]')
  await expect(figurePreview).toBeVisible()
  await expect.poll(() => figurePreview.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)
  await expect(page.getByTestId('artifact-roles')).toContainText('它回答什么')
  await expect(page.getByTestId('artifact-roles')).toContainText('不能据此断言')

  await page.getByRole('button', { name: '证据', exact: true }).click()
  const figureAnchor = page.locator('.anchor-catalog button').filter({ hasText: 'ev-3' })
  await figureAnchor.click()
  await expect(page.getByTestId('evidence-inspector')).toContainText('Figure 1 · 第 4 页')
  await expect(page.getByTestId('evidence-inspector')).toContainText('客观版面层')
  await expect(page.getByTestId('evidence-usage')).toContainText('参与支撑的Claim')
  await expect(page.getByTestId('evidence-usage')).toContainText('对应图表')
  await expect(page.locator('.page-controls')).toContainText('第 4 / 20 页')
  await expect(page.locator('.preview-status')).toContainText('Figure 1')
  await expect(pdfImage).toHaveAttribute('src', /document-preview\/artifacts\/art-1/)
  await expect.poll(() => pdfImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)

  await page.getByRole('button', { name: '论证路径', exact: true }).click()
  const graphPanel = page.getByTestId('paper-evidence-graph')
  await expect(graphPanel).toContainText('neo4j')
  await expect(graphPanel).toContainText('30 节点 / 65 关系')
  await expect(graphPanel).toContainText('MySQL 是事实源')
  await expect(page.getByTestId('graph-path')).toHaveCount(5)

  await page.goto('/knowledge-graph')
  await expect(page).toHaveURL(new RegExp(`/papers/${paperId}\\?tab=graph`))
  await expect(page.getByTestId('paper-evidence-graph')).toContainText('neo4j')
})
