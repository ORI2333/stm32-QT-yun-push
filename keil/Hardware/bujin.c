#include "stm32f10x.h"    
#include "delay.h"
#include "sys.h"  
#include "Periph_GPIO_Init.H"
#include "bujin.h"


void bujin_Init(void)
{
	Periph_GPIO_Init(RCC_APB2Periph_GPIOB,GPIOB,GPIO_Pin_12 | GPIO_Pin_13);

}

//细分
//  x==1 全步
//  x==2 半步 
//  x==4 1/4步
//  x==8 1/8步
//  x==16 1/16步
//void Step_Micr(u16 x)
//{
//	switch(x)
//	{
//		case 1:Full_step;break;
//		case 2:Half_step;break;
//		case 4:Quarter_step;break;
//		case 8:Eighth_step;break;
//		case 16:Sixteenth_step;break;
//		default:break;
//    }   
//}



//参数
//dir:FALSE正转TRUE反转
//period 周期 每步距的延时时间
//step   脉冲
void Step_Control(u8 dir,u16 period,u32 steps)  //1.8步距角  200步一圈
{
	u32 i;
	for(i=0; i <= steps;i++)
	{
		DIR = dir;
		STEP = 1;
		Delay_us(period);
		STEP = 0;
	}
}

//此函数可抱死
//  0 抱死
//  1 正常
void Step_Enable()
{
	ENABLE = 0;
}

