import { toolInputJsonSchema } from './tool-catalog.mjs';
import { toolOutputJsonSchema } from './tool-output-contracts.mjs';
import { TOOL_WORKFLOW_BINDINGS } from './tool-workflow-bindings.mjs';

function decodePointerSegment(segment) {
  return segment.replace(/~1/g, '/').replace(/~0/g, '~');
}

function pointerSegments(pointer) {
  if (pointer === '') return [];
  if (typeof pointer !== 'string' || !pointer.startsWith('/')) return null;
  return pointer.slice(1).split('/').map(decodePointerSegment);
}

function expandVariants(schema) {
  if (Array.isArray(schema?.anyOf) && schema.anyOf.length) return schema.anyOf.flatMap(expandVariants);
  return [schema];
}

function nonNullVariants(schema) {
  return expandVariants(schema).filter((variant) => variant?.type !== 'null');
}

function schemasAtPointer(schema, pointer) {
  const segments = pointerSegments(pointer);
  if (!segments) return [];
  let candidates = expandVariants(schema);
  for (const segment of segments) {
    const next = [];
    for (const candidate of candidates) {
      for (const variant of expandVariants(candidate)) {
        const child = variant?.type === 'object' ? variant.properties?.[segment] : undefined;
        if (child) next.push(...expandVariants(child));
      }
    }
    if (next.length === 0) return [];
    candidates = next;
  }
  return candidates;
}

function enumAssignable(source, target) {
  if (!Array.isArray(target?.enum) || target.enum.length === 0) return true;
  if (!Array.isArray(source?.enum) || source.enum.length === 0) return false;
  const allowed = new Set(target.enum.map((value) => JSON.stringify(value)));
  return source.enum.every((value) => allowed.has(JSON.stringify(value)));
}

function variantAssignable(source, target) {
  if (!source || !target) return true;
  if (Array.isArray(target.anyOf) && target.anyOf.length) {
    return target.anyOf.some((candidate) => variantAssignable(source, candidate));
  }
  if (Array.isArray(source.anyOf) && source.anyOf.length) {
    return nonNullVariants(source).every((candidate) => variantAssignable(candidate, target));
  }

  const sourceType = source.type;
  const targetType = target.type;
  if (!sourceType || !targetType) return true;
  if (sourceType === 'null') return true;
  if (sourceType === 'integer' && targetType === 'number') return true;
  if (sourceType !== targetType) return false;
  if (!enumAssignable(source, target)) return false;

  if (sourceType === 'array') {
    if (!source.items || !target.items) return true;
    return schemaAssignable(source.items, target.items);
  }
  return true;
}

export function schemaAssignable(source, target) {
  const sourceVariants = nonNullVariants(source);
  if (sourceVariants.length === 0) return true;
  return sourceVariants.every((sourceVariant) => {
    const targetVariants = nonNullVariants(target);
    if (targetVariants.length === 0) return true;
    return targetVariants.some((targetVariant) => variantAssignable(sourceVariant, targetVariant));
  });
}

function sourceContract(toolName, sourceKind) {
  if (sourceKind === 'arguments') return toolInputJsonSchema(toolName);
  if (sourceKind === 'structuredContent') return toolOutputJsonSchema(toolName);
  return null;
}

function bindingSourceSchemas(sourceTool, binding) {
  return schemasAtPointer(sourceContract(sourceTool, binding.source), binding.pointer);
}

function bindingTargetSchema(targetTool, binding) {
  const target = toolInputJsonSchema(targetTool).properties?.[binding.target];
  if (binding.transform === 'singleton-array') return target?.items || null;
  return target || null;
}

function selectedSchemas(sourceTool, source) {
  const output = toolOutputJsonSchema(sourceTool);
  const collections = schemasAtPointer(output, source.collectionPointer)
    .filter((candidate) => candidate?.type === 'array' && candidate.items)
    .map((candidate) => candidate.items);
  if (source.itemPointer === '') return collections.flatMap(expandVariants);
  return collections.flatMap((itemSchema) => schemasAtPointer(itemSchema, source.itemPointer));
}

function selectionTargetSchema(targetTool, selection) {
  const target = toolInputJsonSchema(targetTool).properties?.[selection.target];
  if (selection.cardinality === 'many') return target?.items || null;
  return target || null;
}

function assertSchemasAssignable(label, sources, target) {
  if (!target || sources.length === 0) return;
  for (const source of sources) {
    if (!schemaAssignable(source, target)) {
      throw new Error(`Workflow schema type mismatch for ${label}: source ${source?.type || 'open'} is not assignable to target ${target?.type || 'open'}`);
    }
  }
}

export function assertCurrentWorkflowBindingTypeSafety() {
  for (const [sourceTool, workflow] of Object.entries(TOOL_WORKFLOW_BINDINGS)) {
    for (const relation of workflow.relations) {
      for (const binding of relation.bindings || []) {
        const target = bindingTargetSchema(relation.tool, binding);
        assertSchemasAssignable(
          `${sourceTool} -> ${relation.tool}.${binding.target} (${binding.transform})`,
          bindingSourceSchemas(sourceTool, binding),
          target
        );
      }
      for (const selection of relation.selections || []) {
        const target = selectionTargetSchema(relation.tool, selection);
        for (const source of selection.sources || []) {
          assertSchemasAssignable(
            `${sourceTool} -> ${relation.tool}.${selection.target} selection`,
            selectedSchemas(sourceTool, source),
            target
          );
        }
      }
    }
  }
  return true;
}
