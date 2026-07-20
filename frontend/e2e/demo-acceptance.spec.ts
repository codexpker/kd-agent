import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const syntheticCsv = fileURLToPath(
  new URL('../../backend/app/data/evaluation/synthetic_plot_smoke.csv', import.meta.url),
)
const backendOrigin = 'http://127.0.0.1:8010'

test('synthetic_smoke_test: offline golden demo remains evidence-bounded and executable', async ({ page, request }) => {
  const health = await request.get(`${backendOrigin}/api/v1/healthz`)
  expect(health.ok()).toBeTruthy()
  expect(await health.json()).toMatchObject({ status: 'ok', mode: 'offline-ready' })

  const structure = await request.get(
    `${backendOrigin}/api/v1/papers/anomaly-transformer-2022/document-structure`,
  )
  expect(structure.ok()).toBeTruthy()
  const structurePayload = await structure.json()
  expect(structurePayload.source).toBe('gold_snapshot')
  expect(structurePayload.artifacts.length).toBeGreaterThan(0)
  expect(
    structurePayload.artifacts.every(
      (item: { page: number | null }) => item.page === null,
    ),
  ).toBeTruthy()
  expect(structurePayload.warnings.length).toBeGreaterThan(0)

  const graph = await request.get(
    `${backendOrigin}/api/v1/papers/anomaly-transformer-2022/evidence-graph`,
  )
  expect(graph.ok()).toBeTruthy()
  const graphPayload = await graph.json()
  expect(graphPayload.source).toBe('gold_snapshot')
  expect(graphPayload.nodes).toHaveLength(30)
  expect(graphPayload.edges).toHaveLength(65)

  await page.goto('/assistant')
  await expect(page.getByTestId('assistant-shell')).toBeVisible()
  await expect(page.getByText('API 在线 · 离线证据模式', { exact: true })).toBeVisible()
  await expect(page.getByTestId('graph-source')).toHaveText('gold_snapshot')
  await expect(page.getByTestId('quick-task-paper')).toBeVisible()
  await expect(page.getByTestId('quick-task-opportunity')).toBeVisible()
  await expect(page.getByTestId('quick-task-claim')).toBeVisible()
  await expect(page.getByTestId('quick-task-plot')).toBeVisible()
  await page.getByTestId('run-evidence-demo').click()
  await expect(page.getByRole('heading', { name: '拆解一篇论文', exact: true })).toBeVisible()
  await expect(page.locator('.task-status li.done')).toHaveCount(3)
  await expect(page.getByTestId('assistant-runtime')).toHaveText('离线规则 · 本地证据工具')
  await expect(page.getByTestId('assistant-tool-runs')).toContainText('paper_deconstruct')
  await expect(page.getByTestId('assistant-trace')).toContainText('trace_')
  await expect(page.getByTestId('assistant-trace')).toContainText('paper-evidence-chat-v1')
  await page.getByLabel('科研任务输入').fill('这篇论文的证据在PDF第几页？')
  await page.getByRole('button', { name: '发送任务' }).click()
  await expect(page.getByTestId('assistant-tool-runs')).toContainText('document_structure')
  await expect(page.locator('.message-list article.assistant').last()).toContainText('不能把这些位置补出来')
  await page.getByRole('button', { name: '关系图', exact: true }).click()
  await expect(page.getByTestId('evidence-graph')).toContainText('当前 Claim · cl-2')
  await expect(page.getByTestId('assistant-graph-path')).toHaveCount(4)

  await page.goto('/papers/anomaly-transformer-2022')
  await expect(page.getByTestId('paper-reader')).toBeVisible()
  await expect(page.getByTestId('reader-integrity')).toContainText('不是已授权 PDF 阅读页')
  await expect(page.getByTestId('pdf-permission-state')).toContainText('原文未在网页分发')
  await expect(page.getByTestId('narrative-chain').locator('ol > li')).toHaveCount(8)
  await expect(page.getByTestId('evidence-inspector')).toContainText('没有可匹配的自动解析位置')
  await expect(page.getByRole('button', { name: '没有可匹配的自动解析位置' })).toBeDisabled()
  await page.getByRole('button', { name: '实验意图', exact: true }).last().click()
  await expect(page.getByTestId('experiment-intents').locator(':scope > article')).toHaveCount(2)
  await page.getByRole('button', { name: 'Figure / Table', exact: true }).click()
  await expect(page.getByTestId('artifact-roles').locator(':scope > article')).toHaveCount(5)
  await page.getByRole('button', { name: '证据关系', exact: true }).click()
  await expect(page.getByTestId('paper-evidence-graph').locator('svg g')).toHaveCount(10)

  await page.goto('/workspace')
  await expect(page.getByText('开发种子，不是冻结 Gold', { exact: true })).toBeVisible()
  await expect(page.getByText('查询来源：gold_snapshot', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '运行证据分析' }).click()
  await expect(page.getByText('insufficient_evidence', { exact: true })).toBeVisible()
  await expect(page.getByText('当前没有满足至少两篇已审核、已核验证据论文覆盖的候选。')).toBeVisible()

  await page.getByTestId('load-tad-example').click()
  await page.getByTestId('project-id').fill('demo-acceptance')
  await page.getByTestId('save-claim').click()
  await expect(page.getByTestId('claim-diagnosis')).toContainText('Claim v1 · 诊断 r1')
  await expect(page.getByTestId('claim-diagnosis').locator('.requirement-list > article')).toHaveCount(8)

  await page.getByTestId('generate-plan').click()
  await expect(page.getByTestId('plot-workspace')).toBeVisible()
  const runExperiment = page.getByTestId('run-experiment-select')
  await expect(runExperiment).not.toHaveValue('')
  await expect(runExperiment.locator('option:checked')).toContainText('Figure')
  await expect(page.getByTestId('run-artifact-guidance')).toContainText('可继续完成绘图演示')
  const figureExperimentId = await runExperiment.inputValue()
  await runExperiment.selectOption({ label: 'main_experiment · suggested · 0 Figure / 1 Table' })
  await expect(page.getByTestId('run-artifact-guidance')).toContainText('不能用于本轮绘图演示')
  await runExperiment.selectOption(figureExperimentId)

  await page.getByLabel('代码修订', { exact: true }).fill('git:demo-acceptance')
  await page.getByLabel('数据集版本', { exact: true }).fill('synthetic_plot_smoke-v1')
  await page.getByLabel('运行系统', { exact: true }).fill('automated demo acceptance')
  await page.getByLabel('Python 版本', { exact: true }).fill('test-environment')
  await page.getByLabel('硬件摘要', { exact: true }).fill('test-environment')
  await page.getByLabel('框架版本', { exact: true }).fill('not-used-by-smoke-data')
  await page.getByTestId('register-run').click()
  await expect(page.getByTestId('run-manifest')).toContainText('registered')
  await expect(page.getByTestId('run-manifest')).toContainText('self_asserted_local_identity')

  await page.getByTestId('plot-upload-input').setInputFiles(syntheticCsv)
  await page.getByTestId('upload-plot-data').click()
  await expect(page.getByTestId('schema-report')).toContainText('Schema 可继续')
  await expect(page.getByTestId('schema-report')).toContainText('8 行')
  await expect(page.getByTestId('run-manifest')).toContainText('data_attached')

  await page.getByTestId('figure-artifact-select').selectOption({ index: 1 })
  await page.getByTestId('plot-y-column').selectOption('measurement')
  await page.getByTestId('plot-hue-column').selectOption('variant')
  await page.getByTestId('plot-legend-title').fill('Variant')
  await page.getByTestId('plot-title').fill('Synthetic smoke measurement by condition')
  await page.getByTestId('plot-x-label').fill('Condition')
  await page.getByTestId('plot-y-label').fill('Measurement')
  await page.getByTestId('generate-plot-code').click()
  await expect(page.getByTestId('plot-result')).toContainText('matplotlib-traceable-v1')
  await expect(page.getByTestId('plot-result').locator('.plot-checks article.error')).toHaveCount(0)

  await page.getByTestId('execute-plot-code').click()
  await expect(page.getByTestId('run-manifest')).toContainText('plot_succeeded', { timeout: 30_000 })
  const image = page.getByTestId('plot-result-image')
  await expect(image).toBeVisible()
  expect(await image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0)

  const traceabilityLink = page.getByRole('link', { name: '逐点溯源 JSON' })
  const traceabilityHref = await traceabilityLink.getAttribute('href')
  expect(traceabilityHref).toBeTruthy()
  const traceabilityResponse = await request.get(new URL(traceabilityHref!, page.url()).href)
  expect(traceabilityResponse.ok()).toBeTruthy()
  const traceability = await traceabilityResponse.json()
  expect(traceability.schema_version).toBe('plot-traceability-v1')
  expect(traceability.points).toHaveLength(4)
  expect(traceability.points.every(
    (point: { source_rows: number[]; aggregation_rule: string }) => (
      point.source_rows.length > 0
      && point.aggregation_rule === 'arithmetic_mean_plus_minus_sample_standard_deviation'
    ),
  )).toBeTruthy()

  await expect(page.getByRole('link', { name: 'figure.png' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'figure.svg' })).toBeVisible()
  await expect(page.getByRole('link', { name: '下载完整可复现包' })).toBeVisible()
  for (const linkName of ['figure.png', 'figure.svg', '下载完整可复现包']) {
    const href = await page.getByRole('link', { name: linkName }).getAttribute('href')
    expect(href).toBeTruthy()
    expect((await request.get(new URL(href!, page.url()).href)).ok()).toBeTruthy()
  }
  await expect(page.getByText('synthetic_plot_smoke.csv', { exact: true })).toBeVisible()
})
