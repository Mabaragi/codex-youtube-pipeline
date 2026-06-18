declare module "elkjs/lib/elk.bundled.js" {
  export default class ELK {
    layout(graph: unknown): Promise<{
      children?: Array<{ id: string; x?: number; y?: number }>;
    }>;
  }
}
