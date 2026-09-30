import { Controller, Get, Render } from '@nestjs/common';

@Controller()
export class AppController {
  @Get()
  @Render('index')
  root() {
    return { title: 'Agentic SaaS Architect (NestJS)' };
  }

  @Get('/analytics')
  @Render('analytics')
  analytics() {
    return { title: 'LLM Analytics Dashboard' };
  }

  @Get('/pipeline')
  @Render('pipeline')
  pipeline() {
    return { title: 'Scheduled Pipeline' };
  }

  @Get('/scheduled-approval')
  @Render('scheduled-approval')
  scheduledApprovalDefault() {
    return { title: 'OmniShell - Scheduled Approval Window & Document' };
  }

  @Get('/scheduled-approval/:token')
  @Render('scheduled-approval')
  scheduledApproval() {
    return { title: 'OmniShell - Scheduled Approval Window & Document' };
  }
}
