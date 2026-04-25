#ifndef __BUJIN_H_
#define __BUJIN_H_


//#define MS3 PBout(12)		//MS3
//#define MS2 PBout(11)		//MS2
//#define MS1 PBout(10)		//MS1

#define ENABLE PBout(13)//ENABLE

#define DIR PBout(12) 		//dir
#define STEP PBout(13)		//step

//œ∏∑÷∫Í∂®“Â
#define Full_step {MS1 = 0;MS2 = 0;MS3 = 0;}                  
#define Half_step {MS1 = 1;MS2 = 0;MS3 = 0;}
#define Quarter_step {MS1 = 0;MS2 = 1;MS3 = 0;} 
#define Eighth_step {MS1 = 1;MS2 = 1;MS3 = 0;}
#define Sixteenth_step {MS1 = 1;MS2 = 1;MS3 = 1;} 

void bujin_Init(void);

void Step_Control(u8 dir,u16 period,u32 steps);

void Step_Enable(void);
void Step_Control(u8 dir,u16 period,u32 steps);


#endif 


