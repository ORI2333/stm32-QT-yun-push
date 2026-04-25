#ifndef __PWM_H
#define __PWM_H
void Servo_PWM_Init(void);
void PWM_Init(void);
void PWM_SetCompare2(uint16_t Compare);
void PWM_SetCompare1(uint16_t Compare);
void PWM_SetCompare3(uint16_t Compare);
void Servo_SetAngle_TIM1(float Angle);
void Servo_SetAngle(float Angle,uint16_t Servo_Num);
#endif
