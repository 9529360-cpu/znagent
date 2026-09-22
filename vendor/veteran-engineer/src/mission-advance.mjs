import { MissionAdvanceService as CoreMissionAdvanceService } from './mission-advance-core.mjs';
import { MissionExecutionLeaseManager } from './mission-execution-lease.mjs';

export class MissionAdvanceService extends CoreMissionAdvanceService {
  constructor(options) {
    super(options);
    this.missionExecutionLeaseManager = new MissionExecutionLeaseManager({ store: options.store });
  }

  async advance(args) {
    const { mission } = await this.missionService.status({ missionId: args.missionId });
    if (mission.phase !== 'execution') return super.advance(args);
    const executionLease = await this.missionExecutionLeaseManager.acquire({
      missionId: args.missionId,
      operation: 'mission-advance-execution'
    });
    try {
      return await super.advance(args);
    } finally {
      await executionLease.release();
    }
  }
}
