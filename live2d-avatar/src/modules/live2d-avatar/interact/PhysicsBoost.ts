export class SpringValue {
  value = 0;
  velocity = 0;
  target = 0;

  constructor(public stiffness = 120, public damping = 12) {}

  setTarget(value: number): void {
    this.target = value;
  }

  kick(velocity: number): void {
    this.velocity += velocity;
  }

  setDamping(damping: number): void {
    this.damping = damping;
  }

  update(dt: number): void {
    const step = Math.min(Math.max(dt, 0), 0.05);
    const acceleration = (this.target - this.value) * this.stiffness - this.velocity * this.damping;
    this.velocity += acceleration * step;
    this.value += this.velocity * step;
  }

  reset(): void {
    this.value = 0;
    this.velocity = 0;
    this.target = 0;
  }
}
