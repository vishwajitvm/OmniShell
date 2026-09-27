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
}
